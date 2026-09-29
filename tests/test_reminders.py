import asyncio
from datetime import datetime, timedelta

import pytest

from helpers import ctx
from jarvis.core.announcer import Announcer
from jarvis.core.config import Config
from jarvis.core.db import Database
from jarvis.core.event_bus import WILDCARD, EventBus
from jarvis.core.presence import Presence
from jarvis.core.settings import Settings
from jarvis.core.timeutil import KST
from jarvis.skills.reminders import ReminderService


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def build(tmp_path, now=None, db=None, quiet="02:00-08:00"):
    clock = Clock(now or datetime(2026, 9, 29, 21, 47, tzinfo=KST))
    bus = EventBus()
    events = []
    bus.subscribe(WILDCARD, events.append)
    config = Config.model_validate({"quiet_hours": quiet})
    settings = Settings(bus, config, None)
    presence = Presence(bus)
    announcer = Announcer(bus, settings, presence, clock)
    spoken = []

    async def speaker(text, sound):
        spoken.append(text)

    announcer.speaker = speaker
    service = ReminderService(db or Database(tmp_path / "j.db"), bus, announcer, clock)
    return service, clock, events, spoken, presence


def alerts(events):
    return [e.payload for e in events if e.type == "alert" and e.payload.get("active")]


async def test_fire_once_and_mark_done(tmp_path):
    service, clock, events, spoken, _ = build(tmp_path)
    await service.create(clock.now + timedelta(minutes=30), "빨래 꺼내기")
    assert await service.fire_due() == 0
    clock.now += timedelta(minutes=30)
    assert await service.fire_due() == 1
    assert spoken == ["지금은 빨래 꺼내기 할 차례예요."]
    assert alerts(events)[0]["kind"] == "reminder"
    assert service.pending() == []


async def test_repeat_is_rescheduled(tmp_path):
    service, clock, _, spoken, _ = build(tmp_path)
    await service.create(datetime(2026, 9, 30, 0, 0, tzinfo=KST), "잘 준비", "daily")
    clock.now = datetime(2026, 9, 30, 0, 0, 1, tzinfo=KST)
    await service.fire_due()
    [r] = service.pending()
    assert r["when"] == "2026-10-01T00:00:00+09:00" and r["repeat"] == "매일"
    assert len(spoken) == 1


async def test_survives_restart(tmp_path):
    service, clock, *_ = build(tmp_path)
    await service.create(clock.now + timedelta(hours=1), "과제 제출")
    service.db.close()
    again, *_ = build(tmp_path)
    assert [r["message"] for r in again.pending()] == ["과제 제출"]


async def test_missed_while_off(tmp_path):
    service, clock, *_ = build(tmp_path)
    await service.create(clock.now + timedelta(minutes=5), "약 먹기")
    await service.create(clock.now + timedelta(minutes=5), "물 마시기", "daily")
    clock.now += timedelta(hours=2)
    await service._handle_missed_at_startup()
    assert service.announcer.take_missed() == ["약 먹기", "물 마시기"]
    assert [r["message"] for r in service.pending()] == ["물 마시기"]  # repeat moved to tomorrow


async def test_quiet_hours_show_but_do_not_speak(tmp_path):
    service, clock, events, spoken, _ = build(tmp_path, now=datetime(2026, 9, 30, 3, 0, tzinfo=KST))
    await service.create(clock.now + timedelta(seconds=1), "알림")
    clock.now += timedelta(seconds=2)
    await service.fire_due()
    assert spoken == [] and len(alerts(events)) == 1


async def test_away_queues_and_stranger_hears_generic(tmp_path):
    service, clock, events, spoken, presence = build(tmp_path)
    await presence.set("away", clock.now)
    await service.create(clock.now + timedelta(seconds=1), "과제 제출")
    clock.now += timedelta(seconds=2)
    await service.fire_due()
    assert spoken == [] and service.announcer.take_missed() == ["지금은 과제 제출 할 차례예요."]

    await presence.set("stranger", clock.now)
    await service.create(clock.now + timedelta(seconds=1), "병원 예약")
    clock.now += timedelta(seconds=2)
    await service.fire_due()
    assert spoken == ["알림이 있어요. 확인해 주세요."]
    assert alerts(events)[-1]["title"] == "알림이 있어요"


async def test_loop_fires_on_time(tmp_path):
    far = datetime.now(KST) + timedelta(hours=12)  # keep quiet hours away from the real clock
    service, clock, _, spoken, _ = build(tmp_path, quiet=f"{far:%H}:00-{far:%H}:30")
    clock_real = lambda: datetime.now(KST)  # noqa: E731
    service.clock = clock_real
    service.announcer.clock = clock_real
    await service.start()
    due = clock_real() + timedelta(seconds=0.4)
    await service.create(due, "테스트")
    for _ in range(40):
        if spoken:
            break
        await asyncio.sleep(0.05)
    await service.stop()
    assert spoken == ["지금은 테스트 할 차례예요."]
    assert clock_real() - due < timedelta(seconds=1.5)


async def test_voice_set_list_cancel(tmp_path):
    service, clock, *_ = build(tmp_path)
    c = ctx()
    reply = await service.handle("30분 뒤에 빨래 꺼내라고 알려줘", "", c)
    assert reply == "30분 뒤인 오후 10시 17분에 빨래 꺼내기, 알려드릴게요."
    reply = await service.handle("매일 밤 12시에 잘 준비하라고 알려줘", "", c)
    assert reply == "매일 오전 12시에 잘 준비, 알려드릴게요."
    assert await service.handle("내일 아침 7시에 깨워줘", "", c) == "내일 오전 7시에 깨워 드릴게요."

    listing = await service.handle("리마인더 뭐 있어?", "리마인더뭐있어", c)
    assert listing.startswith("리마인더가 3개 있어요.")
    assert await service.handle("빨래 알림 취소해줘", "빨래알림취소해줘", c) == "빨래 꺼내기 알림을 취소했어요."
    assert len(service.pending()) == 2
    assert "모두 취소" in await service.handle("알림 전부 취소해줘", "알림전부취소해줘", c)
    assert await service.handle("오늘 저녁 뭐 먹지", "오늘저녁뭐먹지", c) is None


async def test_tools(tmp_path):
    from jarvis.brain.tools import ToolRegistry

    service, clock, *_ = build(tmp_path)
    tools = ToolRegistry()
    service.register_tools(tools)
    out, err = await tools.call(
        "create_reminder", {"when_iso": "2026-09-30T09:00:00+09:00", "message": "출석", "repeat": "weekdays"}
    )
    assert not err and service.pending()[0]["repeat"] == "평일"
    out, err = await tools.call("create_reminder", {"when_iso": "2020-01-01T00:00:00", "message": "x", "repeat": "none"})
    assert "past" in out
    rid = service.pending()[0]["id"]
    out, _ = await tools.call("cancel_reminder", {"id": rid})
    assert '"cancelled": true' in out
