from __future__ import annotations

from jarvis.voice.stt.base import KO_PROMPT, pcm_to_float32


class WhisperCppEngine:
    """whisper.cpp via pywhispercpp."""

    name = "whisper_cpp"

    def __init__(self, model: str = "small", threads: int = 2) -> None:
        self.model_name = model
        self.threads = threads
        self.model = None

    def check(self) -> None:
        import pywhispercpp  # noqa: F401

    def load(self) -> None:
        from pywhispercpp.model import Model

        self.model = Model(
            self.model_name,
            n_threads=self.threads,
            language="ko",
            print_progress=False,
            print_realtime=False,
            single_segment=True,
            no_context=True,
        )

    def transcribe(self, pcm16: bytes) -> str:
        if self.model is None:
            self.load()
        segments = self.model.transcribe(pcm_to_float32(pcm16), initial_prompt=KO_PROMPT)
        return "".join(s.text for s in segments).strip()
