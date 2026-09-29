"""Camera-free decision logic, fed with per-frame observations (unit-testable).

PresenceTracker: owner seen / stranger / nobody → present / stranger / away, with debounce.
DrowsinessMonitor: eye aspect ratio (EAR) and head-down ratio → staged alerts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

Point = tuple[float, float]


def eye_aspect_ratio(eye: Sequence[Point]) -> float:
    """EAR for six eye points p1..p6 (p1/p4 corners): (|p2-p6| + |p3-p5|) / (2|p1-p4|)."""
    p1, p2, p3, p4, p5, p6 = eye
    width = math.dist(p1, p4)
    if width <= 1e-6:
        return 0.0
    return (math.dist(p2, p6) + math.dist(p3, p5)) / (2.0 * width)


def head_down_ratio(right_eye: Point, left_eye: Point, nose: Point) -> float:
    """Vertical eye→nose distance over inter-ocular distance; shrinks as the head pitches down."""
    inter = math.dist(right_eye, left_eye)
    if inter <= 1e-6:
        return 0.0
    eye_y = (right_eye[1] + left_eye[1]) / 2
    return (nose[1] - eye_y) / inter


def is_frontal(right_eye: Point, left_eye: Point, nose: Point, max_offset: float = 0.35) -> bool:
    """Nose roughly centred between the eyes (not turned sideways)."""
    inter = math.dist(right_eye, left_eye)
    if inter <= 1e-6:
        return False
    mid_x = (right_eye[0] + left_eye[0]) / 2
    return abs(nose[0] - mid_x) / inter <= max_offset


@dataclass
class Observation:
    """What one analysed camera frame says (no image data)."""

    t: float
    faces: int
    owner: bool
    stranger: bool
    ear: float | None
    pitch: float | None
    frontal: bool


@dataclass
class PresenceTracker:
    """away after `away_after` seconds without any face; owner/stranger switch after `confirm` seconds."""

    away_after: float = 20.0
    confirm: float = 1.0
    state: str = "unknown"
    _last_face: float | None = None
    _candidate: str | None = None
    _candidate_since: float = 0.0
    away_since: float | None = None

    def feed(self, t: float, owner: bool, stranger: bool) -> tuple[str, str] | None:
        """Returns (previous, new) on a state change."""
        if owner or stranger:
            self._last_face = t
            target = "present" if owner else "stranger"
            if target == self.state:
                self._candidate = None
                return None
            # Owner recognition wins immediately; a stranger needs to be confirmed.
            if target == "present" or (self._candidate == target and t - self._candidate_since >= self.confirm):
                return self._change(target, t)
            if self._candidate != target:
                self._candidate, self._candidate_since = target, t
            return None
        self._candidate = None
        if self.state != "away" and (self._last_face is None or t - self._last_face >= self.away_after):
            if self.state == "unknown" and self._last_face is None and t < self.away_after:
                return None
            return self._change("away", t)
        return None

    def _change(self, new: str, t: float) -> tuple[str, str]:
        old = self.state
        self.state = new
        if new == "away":
            self.away_since = self._last_face if self._last_face is not None else t
        self._candidate = None
        return old, new


@dataclass
class DrowsinessMonitor:
    """Level 1 after eyes closed (or head down) for `closed_sec`; level 2 after `escalate_sec` more;
    then `cooldown_sec` of silence. Blinks never last long enough to count."""

    baseline_ear: float = 0.28
    ear_ratio: float = 0.75
    baseline_pitch: float = 0.9
    pitch_ratio: float = 0.55
    closed_sec: float = 2.5
    escalate_sec: float = 5.0
    cooldown_sec: float = 60.0
    level: int = 0
    _since: float | None = None
    _alert_at: float = 0.0
    _cooldown_until: float = 0.0
    history: list[float] = field(default_factory=list)

    @property
    def ear_threshold(self) -> float:
        return self.baseline_ear * self.ear_ratio

    def score(self, ear: float | None, pitch: float | None) -> float:
        """0..1 drowsiness gauge for the UI."""
        parts = []
        if ear is not None and self.baseline_ear > 0:
            parts.append(max(0.0, min(1.0, 1 - ear / self.baseline_ear)))
        if pitch is not None and self.baseline_pitch > 0:
            parts.append(max(0.0, min(1.0, 1 - pitch / self.baseline_pitch)))
        return round(max(parts), 3) if parts else 0.0

    def feed(self, t: float, ear: float | None, pitch: float | None, frontal: bool) -> int | None:
        """Returns a new alert level (1 or 2), 0 when recovered from an alert, or None."""
        eyes_closed = frontal and ear is not None and ear < self.ear_threshold
        head_down = pitch is not None and self.baseline_pitch > 0 and pitch < self.baseline_pitch * self.pitch_ratio
        drowsy = eyes_closed or head_down
        if not drowsy:
            self._since = None
            if self.level:
                self.level = 0
                self._cooldown_until = t + self.cooldown_sec
                return 0
            return None
        if self._since is None:
            self._since = t
        if t < self._cooldown_until:
            return None
        duration = t - self._since
        if self.level == 0 and duration >= self.closed_sec:
            self.level, self._alert_at = 1, t
            return 1
        if self.level == 1 and t - self._alert_at >= self.escalate_sec:
            self.level = 2
            return 2
        return None

    def reset(self) -> None:
        self._since = None
        self.level = 0
