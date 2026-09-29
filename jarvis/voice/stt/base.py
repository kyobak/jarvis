from __future__ import annotations

import io
import wave
from typing import Protocol

from jarvis.voice.audio import SAMPLE_RATE

# Nudges Whisper toward the vocabulary we expect.
KO_PROMPT = "자비스, 알려줘, 리마인더, 일정, 집중 모드, 스포티파이, 메일, 슬랙."


class STTEngine(Protocol):
    name: str

    def check(self) -> None:
        """Raise ImportError if the backing package is missing (cheap, no model load)."""
        ...

    def load(self) -> None:
        """Load the model (slow; called once in a worker thread)."""
        ...

    def transcribe(self, pcm16: bytes) -> str:
        """Blocking transcription of 16 kHz mono int16 audio."""
        ...


def pcm_to_float32(pcm16: bytes):
    import numpy as np

    return np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0


def pcm_to_wav(pcm16: bytes, rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm16)
    return buf.getvalue()
