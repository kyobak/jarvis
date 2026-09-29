"""Wires config, bus, storage, and the active world together."""

from __future__ import annotations

import logging
from typing import Any

from jarvis.core.config import Config, default_data_dir
from jarvis.core.db import Database
from jarvis.core.event_bus import EventBus
from jarvis.core.state import StateStore

log = logging.getLogger(__name__)


class JarvisApp:
    def __init__(self, config: Config, *, mock: bool, dev: bool = False, db_path: str | None = None) -> None:
        self.config = config
        self.mock = mock
        self.dev = dev or mock
        self.bus = EventBus()
        self.store = StateStore(self.bus)
        self.db = Database(db_path or default_data_dir() / "jarvis.db")
        if mock:
            from jarvis.mocks.world import MockWorld

            self.world = MockWorld(config, self.bus)
        else:
            from jarvis.world import LiveWorld

            self.world = LiveWorld(config, self.bus, self.db, dev=self.dev)

    async def start(self) -> None:
        log.info("starting jarvis (mock=%s, dev=%s)", self.mock, self.dev)
        await self.world.start()

    async def stop(self) -> None:
        await self.world.stop()
        self.db.close()

    async def handle_client(self, message: dict[str, Any]) -> None:
        """Messages sent from the UI over the WebSocket."""
        kind = message.get("type")
        payload = message.get("payload") or {}
        if kind == "ptt":
            await self.world.handle_ptt(bool(payload.get("down")))
        elif kind == "alert_ack":
            await self.world.handle_alert_ack()
        elif kind == "dev":
            if not self.dev:
                log.warning("ignoring dev command outside dev mode")
                return
            await self.world.handle_dev(str(payload.get("action")), payload.get("value"))
        else:
            log.debug("unknown client message type %r", kind)
