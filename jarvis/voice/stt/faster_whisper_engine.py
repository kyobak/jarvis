from __future__ import annotations

from jarvis.voice.stt.base import KO_PROMPT, pcm_to_float32


class FasterWhisperEngine:
    """CTranslate2 Whisper, int8 on CPU."""

    name = "faster_whisper"

    def __init__(self, model: str = "small", threads: int = 2) -> None:
        self.model_name = model
        self.threads = threads
        self.model = None

    def check(self) -> None:
        import faster_whisper  # noqa: F401

    def load(self) -> None:
        from faster_whisper import WhisperModel

        self.model = WhisperModel(self.model_name, device="cpu", compute_type="int8", cpu_threads=self.threads)

    def transcribe(self, pcm16: bytes) -> str:
        if self.model is None:
            self.load()
        segments, _ = self.model.transcribe(
            pcm_to_float32(pcm16),
            language="ko",
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
            initial_prompt=KO_PROMPT,
        )
        return "".join(s.text for s in segments).strip()
