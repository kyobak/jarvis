"""The conversation loop: wake word / push-to-talk → listen → transcribe → think → speak.

A single task consumes microphone frames; the phase decides what each frame is for.
Wake detection pauses while thinking or speaking so Jarvis never hears itself.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Callable

from jarvis.brain.brain import Brain
from jarvis.core.config import VoiceConfig
from jarvis.core.core_state import CoreStateMachine
from jarvis.core.event_bus import EventBus
from jarvis.core.status import StatusBoard
from jarvis.voice.audio import FRAME_SEC, AudioSource, rms_level
from jarvis.voice.stt.base import STTEngine
from jarvis.voice.tts import TTS
from jarvis.voice.vad import Endpointer, make_vad
from jarvis.voice.wakeword import WakeDetector

log = logging.getLogger(__name__)

DIDNT_CATCH = "잘 못 들었어요. 다시 말씀해 주세요."
STT_MISSING = "음성 인식 엔진이 설치되어 있지 않아요."
MIC_UNAVAILABLE = "마이크를 사용할 수 없어요. T 키로 입력해 주세요."


class MockCapture:
    """Pretends someone spoke for a moment; used with the mock microphone."""

    def __init__(self, speak_sec: float = 1.6) -> None:
        self.speak_sec = speak_sec
        self._t = 0.0

    def feed(self, frame: bytes) -> str | None:
        self._t += FRAME_SEC
        return "done" if self._t >= self.speak_sec else None

    def level(self, frame: bytes) -> float:
        env = max(0.0, math.sin(self._t * 5.0)) * (0.6 + 0.4 * math.sin(self._t * 1.3))
        return round(0.08 + 0.8 * env, 3)

    def audio(self) -> bytes:
        return b""


class RealCapture(Endpointer):
    def level(self, frame: bytes) -> float:
        return rms_level(frame)


class VoiceLoop:
    def __init__(
        self,
        config: VoiceConfig,
        bus: EventBus,
        core: CoreStateMachine,
        status: StatusBoard,
        brain: Brain,
        mic: AudioSource,
        stt: STTEngine | None,
        tts: TTS,
        wake: WakeDetector | None = None,
        capture_factory: Callable[[], object] | None = None,
    ) -> None:
        self.config = config
        self.bus = bus
        self.core = core
        self.status = status
        self.brain = brain
        self.mic = mic
        self.stt = stt
        self.tts = tts
        self.wake = wake
        self.capture_factory = capture_factory or self._real_capture
        self.phase = "idle"
        self._capture = None
        self._trigger_source = "ptt"
        self._task: asyncio.Task | None = None
        self._turn: asyncio.Task | None = None
        self._stt_lock = asyncio.Lock()

    def _real_capture(self) -> RealCapture:
        return RealCapture(
            vad=make_vad(),
            silence_sec=self.config.silence_sec,
            max_sec=self.config.max_utterance_sec,
            no_speech_sec=self.config.no_speech_timeout_sec,
        )

    # ---- lifecycle ------------------------------------------------------------

    async def start(self) -> None:
        await self.mic.start()
        await self.status.update(mic=self.mic.state, wake_word=self.wake is not None)
        if self.stt is not None:
            asyncio.create_task(self._warm_stt(), name="stt-warmup")
        self._task = asyncio.create_task(self._run(), name="voice-loop")

    async def stop(self) -> None:
        for task in (self._task, self._turn):
            if task:
                task.cancel()
        await self.tts.stop()
        await self.mic.stop()

    async def _warm_stt(self) -> None:
        t0 = time.monotonic()
        try:
            async with self._stt_lock:
                await asyncio.to_thread(self.stt.load)
            log.info("STT %s ready in %.1fs", self.stt.name, time.monotonic() - t0)
        except Exception:
            log.exception("STT model failed to load")
            self.stt = None

    # ---- triggers -------------------------------------------------------------

    async def _interrupt(self) -> None:
        """Cut off a reply in progress or abandon listening, so a new request can start."""
        if self.phase == "speaking":
            await self.tts.stop()
            if self._turn:
                await asyncio.wait({self._turn})
        elif self.phase == "listening":
            self._capture = None
            self.phase = "idle"

    async def push_to_talk(self) -> None:
        """Space bar / mic button. Interrupts speech; ignored while thinking."""
        if self.phase == "speaking":
            await self._interrupt()
        if self.phase != "idle":
            return
        if self.mic.state not in ("on", "mock"):
            # No frames will ever arrive; explain instead of listening forever.
            self.phase = "speaking"
            self._turn = asyncio.create_task(self._speak(MIC_UNAVAILABLE))
            return
        await self._begin_listening("ptt")

    async def say_text(self, text: str) -> bool:
        """Typed command: skip the microphone and STT. Returns False if busy thinking."""
        await self._interrupt()
        if self.phase != "idle":
            return False
        self.phase = "thinking"
        self._turn = asyncio.create_task(self._respond(text, time.monotonic()))
        return True

    async def _begin_listening(self, source: str) -> None:
        self._trigger_source = source
        self._capture = self.capture_factory()
        self.phase = "listening"
        await self.core.set_voice("listening")

    # ---- frame loop -------------------------------------------------------------

    async def _run(self) -> None:
        try:
            async for frame in self.mic.frames():
                if self.phase == "idle":
                    if self.wake is not None and await asyncio.to_thread(self.wake.process, frame):
                        await self._begin_listening("wake")
                elif self.phase == "listening" and self._capture is not None:
                    await self.bus.publish("level", {"v": self._capture.level(frame)})
                    result = self._capture.feed(frame)
                    if result is not None:
                        audio = self._capture.audio()
                        self._capture = None
                        self.phase = "thinking"
                        self._turn = asyncio.create_task(self._process(audio, result))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("voice loop crashed")
            await self.status.update(mic="error")

    # ---- one turn ---------------------------------------------------------------

    async def _process(self, audio: bytes, result: str) -> None:
        t0 = time.monotonic()
        try:
            await self.bus.publish("level", {"v": 0})
            if result == "no_speech":
                return await self._finish()
            await self.core.set_voice("thinking")
            if self.stt is None:
                return await self._speak(STT_MISSING)
            async with self._stt_lock:
                text = await asyncio.to_thread(self.stt.transcribe, audio)
            log.info("STT %.2fs: %r", time.monotonic() - t0, text)
            if not text.strip():
                # A false wake is better ignored than answered.
                return await (self._speak(DIDNT_CATCH) if self._trigger_source == "ptt" else self._finish())
            await self._respond(text, t0)
        except Exception:
            log.exception("voice turn failed")
            await self._finish()

    async def _respond(self, text: str, t0: float) -> None:
        try:
            await self.core.set_voice("thinking")
            await self.bus.publish("transcript", {"role": "user", "text": text, "final": True})
            reply = await self.brain.handle(text)
            log.info("reply via %s after %.2fs total", reply.source, time.monotonic() - t0)
            if reply.text:
                await self.bus.publish(
                    "transcript", {"role": "jarvis", "text": reply.text, "final": True, "source": reply.source}
                )
                await self._speak(reply.text, announce=False)
            else:
                await self._finish()
        except Exception:
            log.exception("voice turn failed")
            await self._finish()

    async def _speak(self, text: str, announce: bool = True) -> None:
        if announce:
            await self.bus.publish("transcript", {"role": "jarvis", "text": text, "final": True, "source": "local"})
        self.phase = "speaking"
        await self.core.set_voice("speaking")

        async def level(v: float) -> None:
            await self.bus.publish("level", {"v": v})

        try:
            await self.tts.speak(text, level)
        finally:
            await self._finish()

    async def _finish(self) -> None:
        if self.wake is not None:
            self.wake.reset()
        self.phase = "idle"
        await self.core.set_voice("idle")
