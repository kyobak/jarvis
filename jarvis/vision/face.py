"""Face detection (YuNet), identity (SFace), and eye landmarks (MediaPipe or OpenCV LBF)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import cv2
import numpy as np

from jarvis.vision.logic import Point, eye_aspect_ratio, head_down_ratio, is_frontal
from jarvis.vision.models import model_path

log = logging.getLogger(__name__)

SFACE_MATCH = 0.363  # OpenCV's recommended cosine threshold for SFace
# MediaPipe face mesh eye contours, p1..p6 (p1/p4 corners).
MP_RIGHT_EYE = (33, 160, 158, 133, 153, 144)
MP_LEFT_EYE = (362, 385, 387, 263, 373, 380)
# 68-point (iBUG) layout used by LBF.
LBF_RIGHT_EYE = (36, 37, 38, 39, 40, 41)
LBF_LEFT_EYE = (42, 43, 44, 45, 46, 47)


@dataclass
class Face:
    row: np.ndarray  # YuNet row: x, y, w, h, 5 landmarks (10 values), score
    box: tuple[int, int, int, int]
    right_eye: Point
    left_eye: Point
    nose: Point
    score: float

    @property
    def area(self) -> int:
        return self.box[2] * self.box[3]

    @property
    def frontal(self) -> bool:
        return is_frontal(self.right_eye, self.left_eye, self.nose)

    @property
    def pitch(self) -> float:
        return head_down_ratio(self.right_eye, self.left_eye, self.nose)


class FaceEngine:
    def __init__(self, width: int = 320, height: int = 240, score_threshold: float = 0.8) -> None:
        self.detector = cv2.FaceDetectorYN.create(str(model_path("yunet")), "", (width, height), score_threshold)
        self.recognizer = cv2.FaceRecognizerSF.create(str(model_path("sface")), "")
        self._size = (width, height)

    def detect(self, frame: np.ndarray) -> list[Face]:
        h, w = frame.shape[:2]
        if (w, h) != self._size:
            self.detector.setInputSize((w, h))
            self._size = (w, h)
        _, rows = self.detector.detect(frame)
        faces = []
        for row in rows if rows is not None else []:
            x, y, fw, fh = (int(v) for v in row[:4])
            faces.append(
                Face(row, (x, y, fw, fh), (float(row[4]), float(row[5])), (float(row[6]), float(row[7])),
                     (float(row[8]), float(row[9])), float(row[14]))
            )
        faces.sort(key=lambda f: f.area, reverse=True)
        return faces

    def embedding(self, frame: np.ndarray, face: Face) -> np.ndarray:
        aligned = self.recognizer.alignCrop(frame, face.row)
        feat = self.recognizer.feature(aligned).flatten().astype(np.float32)
        return feat / (np.linalg.norm(feat) + 1e-9)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9))


class EyeLandmarks(Protocol):
    name: str

    def eyes(self, frame: np.ndarray, face: Face) -> tuple[Sequence[Point], Sequence[Point]] | None: ...


class MediaPipeEyes:
    name = "mediapipe"

    def __init__(self) -> None:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision

        self._mp = mp
        options = mp_vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model_path("face_landmarker"))),
            running_mode=mp_vision.RunningMode.IMAGE,
            num_faces=1,
        )
        self.landmarker = mp_vision.FaceLandmarker.create_from_options(options)

    def eyes(self, frame: np.ndarray, face: Face):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self.landmarker.detect(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb))
        if not result.face_landmarks:
            return None
        pts = result.face_landmarks[0]
        h, w = frame.shape[:2]
        pick = lambda idx: [(pts[i].x * w, pts[i].y * h) for i in idx]  # noqa: E731
        return pick(MP_RIGHT_EYE), pick(MP_LEFT_EYE)


class LbfEyes:
    name = "lbf"

    def __init__(self) -> None:
        self.facemark = cv2.face.createFacemarkLBF()
        self.facemark.loadModel(str(model_path("lbf")))

    def eyes(self, frame: np.ndarray, face: Face):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ok, landmarks = self.facemark.fit(gray, np.array([face.box], dtype=np.int32))
        if not ok or not len(landmarks):
            return None
        pts = landmarks[0][0]
        pick = lambda idx: [(float(pts[i][0]), float(pts[i][1])) for i in idx]  # noqa: E731
        return pick(LBF_RIGHT_EYE), pick(LBF_LEFT_EYE)


def make_eye_landmarks(prefer: str = "auto") -> EyeLandmarks | None:
    order = ("mediapipe", "lbf") if prefer == "auto" else (prefer,)
    for name in order:
        try:
            return MediaPipeEyes() if name == "mediapipe" else LbfEyes()
        except Exception as e:  # missing package, model download failure, API drift
            log.info("eye landmarks via %s unavailable: %s", name, e)
    log.warning("no eye landmark backend; drowsiness uses head position only")
    return None


def ear_of(eyes: tuple[Sequence[Point], Sequence[Point]]) -> float:
    return (eye_aspect_ratio(eyes[0]) + eye_aspect_ratio(eyes[1])) / 2


@dataclass
class FaceProfile:
    """What enrollment stores: an averaged identity vector and personal baselines. No images."""

    embedding: np.ndarray
    baseline_ear: float
    baseline_pitch: float

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, embedding=self.embedding, baseline_ear=self.baseline_ear, baseline_pitch=self.baseline_pitch)

    @classmethod
    def load(cls, path: Path) -> "FaceProfile | None":
        if not path.exists():
            return None
        data = np.load(path)
        return cls(data["embedding"], float(data["baseline_ear"]), float(data["baseline_pitch"]))
