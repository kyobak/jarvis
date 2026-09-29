"""Vision (F1, F2): presence → greetings and focus pause; eyes/head → drowsiness alerts.

Sources: the camera worker (real), a synthetic source (mock), or nothing (off / camera
paused / packages missing). Decisions are made by `vision.logic` either way.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from jarvis.core.announcer import Announcer
from jarvis.core.config import Config
from jarvis.core.event_bus import EventBus
from jarvis.core.presence import Presence
from jarvis.core.settings import Settings
from jarvis.core.status import StatusBoard
from jarvis.skills.focus import FocusService
from jarvis.skills.greeter import Greeter
from jarvis.vision.logic import DrowsinessMonitor, Observation, PresenceTracker

log = logging.getLogger(__name__)


class VisionService:
    def __init__(
        self,
        config: Config,
        bus: EventBus,
        status: StatusBoard,
        presence: Presence,
        announcer: Announcer,
        settings: Settings,
        focus: FocusService,
        greeter: Greeter,
        clock: Callable[[], Any],
        mode: str,  # real | mock | off
        profile_path: Path,
    ) -> None:
        self.config = config
        self.bus = bus
        self.status = status
        self.presence = presence
        self.announcer = announcer
        self.settings = settings
        self.focus = focus
        self.greeter = greeter
        self.clock = clock
        self.mode = mode
        self.profile_path = profile_path
        vc = config.vision
        self.tracker = PresenceTracker(away_after=3.0 if mode == "mock" else 20.0)
        self.greet_after_sec = 2.0 if mode == "mock" else vc.greet_after_absence_min * 60
        self.monitor = DrowsinessMonitor(ear_ratio=vc.drowsy_ear_ratio, closed_sec=vc.drowsy_seconds)
        self.enrolled = False
        self.on_wake_alarm: list[Callable[[], Awaitable[None]]] = []  # e.g. play the wake-up playlist
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._tasks: list[asyncio.Task] = []
        self._worker = None
        self._last_publish = 0.0
        self._last_score = 0.0
        # mock controls
        self._mock_absent = False
        self._mock_closed_until = 0.0

    # ---- lifecycle ----------------------------------------------------------------------

    def drowsiness_active(self) -> bool:
        if not self.settings["drowsiness"] or self.focus.napping:
            return False
        now = self.clock()
        return self.focus.active or self.settings.hours("drowsy_hours").contains(now.time())

    def fps(self) -> float:
        return 4.0 if self.drowsiness_active() else 2.0

    async def start(self) -> None:
        self._tasks.append(asyncio.create_task(self._consume(), name="vision-consume"))
        if self.settings["camera_paused"]:
            await self.status.update(camera="paused")
        else:
            await self._open()

    async def stop(self) -> None:
        await self._close()
        for t in self._tasks:
            t.cancel()

    async def set_paused(self, paused: bool) -> None:
        if paused:
            await self._close()
            await self.presence.set("unknown", self.clock())
            await self.status.update(camera="paused")
        else:
            await self._open()

    async def _open(self) -> None:
        if self.mode == "off":
            await self.status.update(camera="off")
            return
        if self.mode == "mock":
            self.enrolled = True
            self._tasks.append(asyncio.create_task(self._mock_source(), name="vision-mock"))
            await self.status.update(camera="mock", face_enrolled=True)
            return
        try:
            from jarvis.vision.face import FaceEngine, FaceProfile, make_eye_landmarks
            from jarvis.vision.worker import VisionWorker
        except ImportError as e:
            log.warning("vision packages missing (%s); install with: uv sync --extra vision", e)
            await self.status.update(camera="off")
            return
        loop = asyncio.get_running_loop()
        try:
            engine, eyes = await asyncio.to_thread(lambda: (FaceEngine(), make_eye_landmarks()))
        except Exception as e:
            log.error("vision models failed to load: %s", e)
            await self.status.update(camera="error")
            return
        profile = FaceProfile.load(self.profile_path)
        self.enrolled = profile is not None
        if profile:
            self.monitor.baseline_ear = profile.baseline_ear
            self.monitor.baseline_pitch = profile.baseline_pitch
        else:
            log.info("no enrolled face: every face counts as the owner (run `jarvis enroll`)")

        def deliver(obs) -> None:
            loop.call_soon_threadsafe(self._offer, obs)

        self._worker = VisionWorker(
            self.config.vision.camera_index, engine, eyes, profile, deliver, self.fps, self.drowsiness_active
        )
        self._worker.start()
        await asyncio.to_thread(self._worker.opened.wait, 10)
        state = "error" if self._worker.error else "on"
        if self._worker.error:
            log.error("camera: %s", self._worker.error)
        await self.status.update(camera=state, face_enrolled=self.enrolled)

    async def _close(self) -> None:
        if self._worker:
            self._worker.stop()
            await asyncio.to_thread(self._worker.join, 3)
            self._worker = None
        for t in [t for t in self._tasks if t.get_name() == "vision-mock"]:
            t.cancel()
            self._tasks.remove(t)

    def _offer(self, obs) -> None:
        if self._queue.full():
            self._queue.get_nowait()
        self._queue.put_nowait(obs)

    # ---- decisions -----------------------------------------------------------------------

    async def _consume(self) -> None:
        while True:
            obs = await self._queue.get()
            try:
                await self.observe(obs)
            except Exception:
                log.exception("vision observation failed")

    async def observe(self, obs) -> None:
        change = self.tracker.feed(obs.t, obs.owner, obs.stranger)
        if change:
            await self._presence_changed(*change, obs.t)
        active = self.drowsiness_active() and obs.owner
        score = self.monitor.score(obs.ear, obs.pitch) if active else 0.0
        if active:
            level = self.monitor.feed(obs.t, obs.ear, obs.pitch, obs.frontal)
            if level is not None:
                await self._drowsy(level)
        elif self.monitor.level:
            self.monitor.reset()
            await self.announcer.clear()
        if obs.t - self._last_publish >= 1.0 or abs(score - self._last_score) > 0.2:
            self._last_publish, self._last_score = obs.t, score
            nap = self.focus.nap_until.isoformat(timespec="minutes") if self.focus.napping else None
            await self.bus.publish("drowsiness", {"score": score, "enabled": self.drowsiness_active(), "nap_until": nap})

    async def _presence_changed(self, old: str, new: str, t: float) -> None:
        log.info("presence %s → %s", old, new)
        await self.presence.set(new, self.clock())
        if new == "away":
            await self.focus.pause()
        elif new == "present":
            await self.focus.resume()
            away_for = t - self.tracker.away_since if old == "away" and self.tracker.away_since is not None else 0
            if old == "unknown" or away_for >= self.greet_after_sec:
                await self.greeter.greet("arrive" if old == "unknown" else "return")

    async def _drowsy(self, level: int) -> None:
        name = self.config.user_name
        if level == 1:
            text = f"{name}님, 졸고 계신 것 같아요."
            await self.announcer.notify("drowsy", text, say=text, level=1, personal=False, force_voice=True)
        elif level == 2:
            text = f"{name}님! 일어나세요!"
            await self.announcer.notify("drowsy", text, say=text, level=2, personal=False, sound="Sosumi", force_voice=True)
            for hook in self.on_wake_alarm:
                try:
                    await hook()
                except Exception:
                    log.exception("wake alarm hook failed")
        else:
            await self.announcer.clear()

    # ---- mock ------------------------------------------------------------------------------------

    async def _mock_source(self) -> None:
        base = self.monitor.baseline_ear
        t0 = time.monotonic()
        while True:
            await asyncio.sleep(0.25)
            t = time.monotonic()
            if self._mock_absent:
                await self.observe(Observation(t, 0, False, False, None, None, False))
                continue
            closed = t < self._mock_closed_until
            ear = base * (0.2 if closed else 1 + 0.08 * math.sin((t - t0) / 3) + random.uniform(-0.03, 0.03))
            await self.observe(Observation(t, 1, True, False, ear, self.monitor.baseline_pitch, True))

    def simulate_drowsy(self, level: int) -> None:
        """Dev key: close the mock eyes long enough to reach `level`."""
        seconds = self.monitor.closed_sec + 0.3 + (self.monitor.escalate_sec if level >= 2 else 0)
        self.monitor._cooldown_until = 0.0
        self._mock_closed_until = time.monotonic() + seconds

    def toggle_absent(self) -> bool:
        self._mock_absent = not self._mock_absent
        return self._mock_absent
