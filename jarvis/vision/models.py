"""Model files, downloaded once into the data directory (no images ever leave the machine)."""

from __future__ import annotations

import logging
import os
import urllib.request
from pathlib import Path

from jarvis.core.config import default_data_dir

log = logging.getLogger(__name__)

MODELS = {
    "yunet": (
        "face_detection_yunet_2023mar.onnx",
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    ),
    "sface": (
        "face_recognition_sface_2021dec.onnx",
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    ),
    "lbf": ("lbfmodel.yaml", "https://raw.githubusercontent.com/kurnianggoro/GSOC2017/master/data/lbfmodel.yaml"),
    "face_landmarker": (
        "face_landmarker.task",
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    ),
}


def models_dir() -> Path:
    return Path(os.environ.get("JARVIS_MODELS_DIR", default_data_dir() / "models"))


def model_path(name: str, download: bool = True) -> Path:
    filename, url = MODELS[name]
    path = models_dir() / filename
    if path.exists() and path.stat().st_size > 1000:
        return path
    if not download:
        raise FileNotFoundError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    log.info("downloading %s model (first run only)…", name)
    with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as f:
        while chunk := resp.read(1 << 16):
            f.write(chunk)
    if tmp.stat().st_size < 1000 or tmp.read_bytes()[:40].lstrip().startswith(b"version https://git-lfs"):
        tmp.unlink()
        raise RuntimeError(f"download of {name} returned a placeholder, not the model")
    tmp.rename(path)
    return path
