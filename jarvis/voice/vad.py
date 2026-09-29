"""Voice activity detection and utterance endpointing."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from jarvis.voice.audio import FRAME_SAMPLES, FRAME_SEC, SAMPLE_RATE, rms_level

log = logging.getLogger(__name__)

EPS = 1e-6  # frame durations accumulate float error (10 × 0.08 < 0.8)


class VAD(Protocol):
    def is_speech(self, frame: bytes) -> bool: ...


class WebRtcVAD:
    """webrtcvad on 20 ms sub-frames; a frame is speech if most sub-frames are."""

    SUB = SAMPLE_RATE * 20 // 1000  # 320 samples

    def __init__(self, aggressiveness: int = 2) -> None:
        import webrtcvad

        self.vad = webrtcvad.Vad(aggressiveness)

    def is_speech(self, frame: bytes) -> bool:
        step = self.SUB * 2
        votes = [self.vad.is_speech(frame[i : i + step], SAMPLE_RATE) for i in range(0, len(frame) - step + 1, step)]
        return sum(votes) * 2 > len(votes)


class EnergyVAD:
    """Fallback: loudness above an adaptive noise floor."""

    def __init__(self, margin: float = 0.18) -> None:
        self.floor = 0.2
        self.margin = margin

    def is_speech(self, frame: bytes) -> bool:
        level = rms_level(frame)
        speech = level > self.floor + self.margin
        if not speech:  # track the noise floor only during silence
            self.floor = 0.95 * self.floor + 0.05 * level
        return speech


def make_vad() -> VAD:
    try:
        return WebRtcVAD()
    except ImportError:
        log.warning("webrtcvad not installed; using energy-based VAD")
        return EnergyVAD()


@dataclass
class Endpointer:
    """Collects one utterance: waits for speech, stops after trailing silence.

    feed() returns None while still listening, else the final status:
    "done" (utterance captured), "no_speech" (nobody spoke), "max" (length cap hit).
    """

    vad: VAD
    silence_sec: float = 0.8
    max_sec: float = 10.0
    no_speech_sec: float = 5.0
    min_speech_sec: float = 0.24
    preroll_frames: int = 4
    frames: list[bytes] = field(default_factory=list)
    _speech_sec: float = 0.0
    _silence_sec: float = 0.0
    _elapsed: float = 0.0
    _started: bool = False

    def feed(self, frame: bytes) -> str | None:
        self._elapsed += FRAME_SEC
        speech = self.vad.is_speech(frame)
        self.frames.append(frame)
        if not self._started:
            self._speech_sec = self._speech_sec + FRAME_SEC if speech else 0.0
            if self._speech_sec >= self.min_speech_sec - EPS:
                self._started = True
                # Keep a little audio from just before speech began.
                keep = int(self._speech_sec / FRAME_SEC) + self.preroll_frames
                self.frames = self.frames[-keep:]
            else:
                self.frames = self.frames[-(self.preroll_frames + 4) :]
                if self._elapsed >= self.no_speech_sec - EPS:
                    return "no_speech"
            return None
        self._silence_sec = 0.0 if speech else self._silence_sec + FRAME_SEC
        if self._silence_sec >= self.silence_sec - EPS:
            return "done"
        if self._elapsed >= self.max_sec - EPS:
            return "max"
        return None

    def audio(self) -> bytes:
        return b"".join(self.frames)

    @property
    def duration(self) -> float:
        return len(self.frames) * FRAME_SAMPLES / SAMPLE_RATE
