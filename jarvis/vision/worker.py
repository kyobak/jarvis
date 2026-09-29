"""Camera thread: capture at a few fps, detect/identify/measure, hand results to asyncio.

Frames stay in this thread's memory; nothing is written to disk or sent anywhere.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import cv2
import numpy as np

from jarvis.vision.face import SFACE_MATCH, EyeLandmarks, FaceEngine, FaceProfile, ear_of, similarity
from jarvis.vision.logic import Observation

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 320, 240
IDENTIFY_EVERY = 2.0  # seconds between identity checks while a face stays in view


class VisionWorker(threading.Thread):
    def __init__(
        self,
        camera_index: int,
        engine: FaceEngine,
        eyes: EyeLandmarks | None,
        profile: FaceProfile | None,
        on_observation: Callable[[Observation], None],
        fps: Callable[[], float],
        want_eyes: Callable[[], bool],
    ) -> None:
        super().__init__(name="vision", daemon=True)
        self.camera_index = camera_index
        self.engine = engine
        self.eyes = eyes
        self.profile = profile
        self.on_observation = on_observation
        self.fps = fps
        self.want_eyes = want_eyes
        self._stop = threading.Event()
        self.error: str | None = None
        self.opened = threading.Event()
        self._identity: tuple[float, bool] | None = None  # (checked_at, is_owner)

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            self.error = "camera could not be opened (permission?)"
            self.opened.set()
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.opened.set()
        failures = 0
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                ok, frame = cap.read()
                if not ok:
                    failures += 1
                    if failures > 20:
                        self.error = "camera stopped delivering frames"
                        return
                    time.sleep(0.2)
                    continue
                failures = 0
                try:
                    self.on_observation(self.analyse(cv2.resize(frame, (WIDTH, HEIGHT)), started))
                except Exception:
                    log.exception("vision frame failed")
                del frame
                delay = 1.0 / max(0.5, self.fps()) - (time.monotonic() - started)
                if delay > 0:
                    self._stop.wait(delay)
        finally:
            cap.release()  # the camera light goes off

    def analyse(self, frame: np.ndarray, t: float) -> Observation:
        faces = self.engine.detect(frame)
        if not faces:
            self._identity = None
            return Observation(t, 0, False, False, None, None, False)
        face = faces[0]
        owner = self._is_owner(frame, face, t)
        ear = None
        if owner and self.eyes is not None and self.want_eyes() and face.frontal:
            eyes = self.eyes.eyes(frame, face)
            ear = ear_of(eyes) if eyes else None
        return Observation(t, len(faces), owner, not owner, ear, face.pitch if owner else None, face.frontal)

    def _is_owner(self, frame: np.ndarray, face, t: float) -> bool:
        if self.profile is None:
            return True  # not enrolled: anyone at the desk counts as the owner
        if self._identity and t - self._identity[0] < IDENTIFY_EVERY:
            return self._identity[1]
        sim = similarity(self.engine.embedding(frame, face), self.profile.embedding)
        self._identity = (t, sim >= SFACE_MATCH)
        return self._identity[1]
