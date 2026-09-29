"""Wake word detection with openWakeWord's pre-trained "hey jarvis" model (local, CPU)."""

from __future__ import annotations

import logging
import time
from typing import Protocol

log = logging.getLogger(__name__)


class WakeDetector(Protocol):
    def process(self, frame: bytes) -> bool:
        """Feed one 80 ms frame; True when the wake word fired."""
        ...

    def reset(self) -> None: ...


class OpenWakeWord:
    def __init__(self, model_name: str = "hey_jarvis", threshold: float = 0.5, cooldown_sec: float = 2.0) -> None:
        import numpy as np

        self._np = np
        self.model = _load_model(model_name)
        self.threshold = threshold
        self.cooldown_sec = cooldown_sec
        self._last_fire = 0.0

    def process(self, frame: bytes) -> bool:
        scores = self.model.predict(self._np.frombuffer(frame, dtype=self._np.int16))
        score = max(scores.values()) if scores else 0.0
        now = time.monotonic()
        if score >= self.threshold and now - self._last_fire > self.cooldown_sec:
            self._last_fire = now
            log.info("wake word (score %.2f)", score)
            return True
        return False

    def reset(self) -> None:
        # Clear buffered audio so our own TTS cannot trigger a wake right after speaking.
        self.model.reset()


def _load_model(model_name: str):
    import openwakeword
    from openwakeword.model import Model

    download = getattr(openwakeword.utils, "download_models", None)
    if download is not None:  # openwakeword >= 0.5: models are downloaded on first use
        try:
            download(model_names=[model_name])
        except Exception as e:  # already cached, or offline
            log.debug("wake model download skipped: %s", e)
        return Model(wakeword_models=[model_name], inference_framework="onnx")
    # openwakeword 0.4.x bundles its models with the package.
    paths = [p for p in openwakeword.get_pretrained_model_paths() if model_name in p]
    if not paths:
        raise FileNotFoundError(f"no bundled wake word model named {model_name}")
    return Model(wakeword_model_paths=paths)


def make_wake_detector(model_name: str, threshold: float) -> WakeDetector | None:
    try:
        return OpenWakeWord(model_name, threshold)
    except ImportError:
        log.warning("openwakeword not installed; wake word disabled (use space / mic button)")
    except Exception:
        log.exception("wake word model failed to load; wake word disabled")
    return None
