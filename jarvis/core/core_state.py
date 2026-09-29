"""Derives the core's visible state from the voice phase and any active alert."""

from __future__ import annotations

from jarvis.core.event_bus import Event, EventBus

VOICE_PHASES = ("idle", "listening", "thinking", "speaking")


class CoreStateMachine:
    """Voice activity wins while it runs; an active alert shows whenever voice is idle."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.voice = "idle"
        self.alert_active = False
        self._published: str | None = None
        bus.subscribe("alert", self._on_alert)

    @property
    def core(self) -> str:
        if self.voice != "idle":
            return self.voice
        return "alert" if self.alert_active else "idle"

    async def set_voice(self, phase: str) -> None:
        if phase not in VOICE_PHASES:
            raise ValueError(phase)
        self.voice = phase
        await self._publish()

    async def _on_alert(self, event: Event) -> None:
        self.alert_active = bool(event.payload.get("active"))
        await self._publish()

    async def _publish(self, force: bool = False) -> None:
        core = self.core
        if force or core != self._published:
            self._published = core
            await self.bus.publish("state", {"core": core})

    async def publish_current(self) -> None:
        await self._publish(force=True)
