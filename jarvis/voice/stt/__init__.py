"""Speech-to-text engines. Pick one with scripts/bench_stt.py and set voice.stt_engine."""

from __future__ import annotations

import logging

from jarvis.voice.stt.base import STTEngine

log = logging.getLogger(__name__)

AUTO_ORDER = ("faster_whisper", "whisper_cpp", "apple")


def create(name: str, model: str = "small") -> STTEngine:
    if name == "faster_whisper":
        from jarvis.voice.stt.faster_whisper_engine import FasterWhisperEngine

        return FasterWhisperEngine(model)
    if name == "whisper_cpp":
        from jarvis.voice.stt.whisper_cpp_engine import WhisperCppEngine

        return WhisperCppEngine(model)
    if name == "apple":
        from jarvis.voice.stt.apple_engine import AppleSpeechEngine

        return AppleSpeechEngine()
    if name == "mock":
        from jarvis.voice.stt.mock_engine import MockEngine

        return MockEngine()
    raise ValueError(f"unknown STT engine {name!r}")


def make_stt(name: str, model: str = "small") -> STTEngine | None:
    """Resolve "auto" to the first engine whose package is importable."""
    names = AUTO_ORDER if name == "auto" else (name,)
    for candidate in names:
        try:
            engine = create(candidate, model)
            engine.check()
            log.info("STT engine: %s", engine.name)
            return engine
        except ImportError as e:
            log.info("STT engine %s unavailable: %s", candidate, e)
    log.error("no STT engine available (install one of: %s)", ", ".join(AUTO_ORDER))
    return None
