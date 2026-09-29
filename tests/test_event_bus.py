from jarvis.core.event_bus import WILDCARD, EventBus
from jarvis.core.state import StateStore


async def test_publish_reaches_typed_and_wildcard_subscribers():
    bus = EventBus()
    seen = []
    bus.subscribe("state", lambda e: seen.append(("typed", e.payload["core"])))
    bus.subscribe(WILDCARD, lambda e: seen.append(("any", e.type)))
    await bus.publish("state", {"core": "idle"})
    assert seen == [("typed", "idle"), ("any", "state")]


async def test_failing_handler_does_not_block_others():
    bus = EventBus()
    seen = []

    def boom(_):
        raise RuntimeError("boom")

    async def ok(e):
        seen.append(e.type)

    bus.subscribe("x", boom)
    bus.subscribe("x", ok)
    await bus.publish("x")
    assert seen == ["x"]


async def test_unsubscribe():
    bus = EventBus()
    seen = []
    unsub = bus.subscribe("x", lambda e: seen.append(1))
    unsub()
    await bus.publish("x")
    assert seen == []


async def test_store_keeps_latest_sticky_only():
    bus = EventBus()
    store = StateStore(bus)
    await bus.publish("state", {"core": "idle"})
    await bus.publish("state", {"core": "thinking"})
    await bus.publish("level", {"v": 0.5})
    assert [e.to_wire() for e in store.snapshot()] == [{"type": "state", "payload": {"core": "thinking"}}]
