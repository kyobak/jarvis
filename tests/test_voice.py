import array
import asyncio
import math
import wave

import pytest

from jarvis.brain.backends.simple import MockBackend
from jarvis.brain.brain import Brain
from jarvis.core.config import Config
from jarvis.core.core_state import CoreStateMachine
from jarvis.core.db import Database
from jarvis.core.event_bus import WILDCARD, EventBus
from jarvis.core.state import StateStore
from jarvis.core.status import StatusBoard
from jarvis.voice.audio import FRAME_SAMPLES, SAMPLE_RATE, downsample, rms_level
from jarvis.voice.loop import MockCapture, VoiceLoop
from jarvis.voice.stt.mock_engine import MockEngine
from jarvis.voice.tts import MockTTS, envelope, speakable
from jarvis.voice.vad import EnergyVAD, Endpointer


def tone(amp: float, n: int = FRAME_SAMPLES) -> bytes:
    return array.array("h", (int(amp * 32767 * math.sin(i * 0.3)) for i in range(n))).tobytes()


SILENT = bytes(FRAME_SAMPLES * 2)
LOUD = tone(0.5)


def test_levels_and_downsample():
    assert rms_level(SILENT) == 0.0
    assert rms_level(LOUD) > 0.8
    assert len(downsample(tone(0.5, 3 * FRAME_SAMPLES), 3)) == FRAME_SAMPLES * 2


def test_endpointer_captures_one_utterance():
    ep = Endpointer(vad=EnergyVAD(), silence_sec=0.8, no_speech_sec=5)
    frames = [SILENT] * 5 + [LOUD] * 10 + [SILENT] * 12
    result, fed = None, 0
    while result is None:
        result = ep.feed(frames[fed])
        fed += 1
    assert result == "done" and fed == 25  # 10 silent frames (0.8 s) after speech
    # Pre-roll + speech + trailing silence, not the whole initial wait.
    assert 1.0 < ep.duration < 2.2


def test_endpointer_gives_up_without_speech():
    ep = Endpointer(vad=EnergyVAD(), no_speech_sec=1.0)
    results = [ep.feed(SILENT) for _ in range(13)]
    assert "no_speech" in results


def test_endpointer_caps_length():
    ep = Endpointer(vad=EnergyVAD(), max_sec=1.0)
    results = [ep.feed(LOUD) for _ in range(20)]
    assert "max" in results


def test_speakable_strips_markdown():
    assert speakable("**좋아요!** 자세한 건 https://x.y 를 보세요\n- 하나") == "좋아요! 자세한 건 를 보세요 하나"


def test_envelope(tmp_path):
    path = tmp_path / "a.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(SILENT * 5 + LOUD * 5)
    env = envelope(path)
    assert env[0] == 0.0 and max(env) > 0.8


# ---- voice loop --------------------------------------------------------------------


class ListMic:
    """Feeds prepared frames, then silence, as fast as the loop consumes them."""

    def __init__(self, frames):
        self.state = "on"
        self.queue = list(frames)

    async def start(self):
        pass

    async def stop(self):
        pass

    async def frames(self):
        while True:
            await asyncio.sleep(0.001)
            yield self.queue.pop(0) if self.queue else SILENT


class FakeWake:
    def __init__(self, fire_on):
        self.fire_on = fire_on
        self.resets = 0

    def process(self, frame):
        return frame == self.fire_on

    def reset(self):
        self.resets += 1


def build(tmp_path, mic, stt, wake=None, capture=None, phrases=None):
    config = Config()
    bus = EventBus()
    events = []
    bus.subscribe(WILDCARD, lambda e: events.append(e) if e.type != "level" else None)
    store = StateStore(bus)
    status = StatusBoard(bus)
    brain = Brain(config, store, Database(tmp_path / "j.db"), status, MockBackend(delay=0))
    core = CoreStateMachine(bus)
    loop = VoiceLoop(
        config.voice, bus, core, status, brain, mic=mic, stt=stt, tts=MockTTS(sec_per_char=0.001),
        wake=wake, capture_factory=capture,
    )
    return loop, events


async def wait_for(pred, timeout=5.0):
    end = asyncio.get_running_loop().time() + timeout
    while not pred():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("timed out")
        await asyncio.sleep(0.01)


def states(events):
    return [e.payload["core"] for e in events if e.type == "state"]


def transcripts(events):
    return [(e.payload["role"], e.payload["text"]) for e in events if e.type == "transcript"]


async def test_push_to_talk_round_trip(tmp_path):
    stt = MockEngine(phrases=("지금 몇 시야?",), delay=0)
    loop, events = build(tmp_path, ListMic([]), stt, capture=lambda: MockCapture(speak_sec=0.2))
    await loop.start()
    await loop.push_to_talk()
    await wait_for(lambda: len(transcripts(events)) == 2 and loop.phase == "idle")
    await loop.stop()
    assert states(events) == ["listening", "thinking", "speaking", "idle"]
    role, reply = transcripts(events)[1]
    assert transcripts(events)[0] == ("user", "지금 몇 시야?")
    assert role == "jarvis" and reply.startswith("지금은 ")


async def test_llm_question_goes_to_backend(tmp_path):
    stt = MockEngine(phrases=("저녁 메뉴 추천해줘",), delay=0)
    loop, events = build(tmp_path, ListMic([]), stt, capture=lambda: MockCapture(speak_sec=0.2))
    await loop.start()
    await loop.push_to_talk()
    await wait_for(lambda: len(transcripts(events)) == 2 and loop.phase == "idle")
    await loop.stop()
    reply = [e for e in events if e.type == "transcript"][1].payload
    assert reply["source"] == "llm" and "모의 모드" in reply["text"]


async def test_wake_word_then_real_endpointing(tmp_path):
    wake_frame = tone(0.01)
    frames = [wake_frame] + [LOUD] * 8 + [SILENT] * 14
    wake = FakeWake(wake_frame)
    stt = MockEngine(phrases=("오늘 며칠이야",), delay=0)
    loop, events = build(tmp_path, ListMic(frames), stt, wake=wake)
    loop.capture_factory = lambda: __import__("jarvis.voice.loop", fromlist=["RealCapture"]).RealCapture(
        vad=EnergyVAD(), silence_sec=0.8
    )
    await loop.start()
    await wait_for(lambda: len(transcripts(events)) == 2 and loop.phase == "idle")
    await loop.stop()
    assert transcripts(events)[1][1].startswith("오늘은 ")
    assert wake.resets >= 1  # cleared after speaking so TTS can't self-trigger


async def test_false_wake_with_silence_is_ignored(tmp_path):
    wake_frame = tone(0.01)
    wake = FakeWake(wake_frame)
    stt = MockEngine(phrases=("안 불려야 함",), delay=0)
    loop, events = build(tmp_path, ListMic([wake_frame]), stt, wake=wake)
    loop.config.no_speech_timeout_sec = 0.3
    await loop.start()
    await wait_for(lambda: "listening" in states(events))
    await wait_for(lambda: loop.phase == "idle" and states(events)[-1] == "idle")
    await loop.stop()
    assert transcripts(events) == []


async def test_typed_command_skips_stt(tmp_path):
    loop, events = build(tmp_path, ListMic([]), stt=None)
    await loop.start()
    await loop.say_text("몇 시야")
    await wait_for(lambda: len(transcripts(events)) == 2 and loop.phase == "idle")
    await loop.stop()
    assert "listening" not in states(events)


async def test_missing_stt_is_explained(tmp_path):
    loop, events = build(tmp_path, ListMic([]), stt=None, capture=lambda: MockCapture(speak_sec=0.1))
    await loop.start()
    await loop.push_to_talk()
    await wait_for(lambda: transcripts(events) and loop.phase == "idle")
    await loop.stop()
    assert "음성 인식 엔진" in transcripts(events)[0][1]


async def test_alert_survives_a_conversation(tmp_path):
    loop, events = build(tmp_path, ListMic([]), MockEngine(("몇 시야",), 0), capture=lambda: MockCapture(0.1))
    await loop.start()
    await loop.bus.publish("alert", {"id": 1, "active": True})
    await loop.push_to_talk()
    await wait_for(lambda: len(transcripts(events)) == 2 and loop.phase == "idle")
    await loop.stop()
    assert states(events)[0] == "alert" and states(events)[-1] == "alert"


async def test_typed_command_interrupts_speech(tmp_path):
    loop, events = build(tmp_path, ListMic([]), stt=None)
    loop.tts = MockTTS(sec_per_char=0.2)  # long enough to interrupt
    await loop.start()
    await loop.say_text("몇 시야")
    await wait_for(lambda: loop.phase == "speaking")
    assert await loop.say_text("며칠이야")
    await wait_for(lambda: len(transcripts(events)) == 4)
    await loop.stop()
    assert transcripts(events)[2] == ("user", "며칠이야")


async def test_unusable_microphone_is_explained_not_stuck(tmp_path):
    mic = ListMic([])
    mic.state = "error"
    loop, events = build(tmp_path, mic, MockEngine(("몇 시야",), 0))
    await loop.start()
    await loop.push_to_talk()
    await wait_for(lambda: loop.phase == "idle" and transcripts(events))
    await loop.stop()
    assert "listening" not in states(events)
    assert "마이크" in transcripts(events)[0][1]
