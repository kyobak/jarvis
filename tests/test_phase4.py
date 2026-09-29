import asyncio
from datetime import datetime, timedelta

from helpers import ctx
from jarvis.core.announcer import Announcer
from jarvis.core.config import Config
from jarvis.core.db import Database
from jarvis.core.event_bus import WILDCARD, EventBus
from jarvis.core.presence import Presence
from jarvis.core.settings import Settings
from jarvis.core.status import StatusBoard
from jarvis.core.timeutil import KST
from jarvis.skills.focus import FocusService
from jarvis.skills.greeter import Greeter
from jarvis.vision.logic import Observation
from jarvis.vision.service import VisionService


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def rig(tmp_path, now=datetime(2026, 9, 29, 21, 0, tzinfo=KST)):
    clock = Clock(now)
    bus = EventBus()
    events = []
    bus.subscribe(WILDCARD, events.append)
    config = Config()
    settings = Settings(bus, config, None)
    presence = Presence(bus)
    announcer = Announcer(bus, settings, presence, clock)
    spoken = []

    async def speaker(text, sound):
        spoken.append(text)

    announcer.speaker = speaker
    focus = FocusService(Database(tmp_path / "j.db"), bus, announcer, clock)
    upcoming = [{"title": "UMC 스터디", "start": now + timedelta(minutes=40), "all_day": False}]
    greeter = Greeter(announcer, settings, clock, "재원", upcoming=lambda n: upcoming,
                      unread=lambda: {"gmail": 3}, today_events=lambda n: upcoming)
    vision = VisionService(config, bus, StatusBoard(bus), presence, announcer, settings, focus, greeter,
                           clock, "off", tmp_path / "p.npz")
    return vision, focus, clock, spoken, events, presence, announcer


def obs(t, owner=True, stranger=False, ear=0.3, pitch=0.9):
    faces = 1 if (owner or stranger) else 0
    return Observation(t, faces, owner, stranger, ear if faces else None, pitch if faces else None, bool(faces))


async def test_focus_session_pause_resume_and_stats(tmp_path):
    _, focus, clock, spoken, *_ = rig(tmp_path)
    await focus.start_focus(50)
    clock.now += timedelta(minutes=10)
    await focus.pause()
    clock.now += timedelta(minutes=30)  # away: does not count
    await focus.resume()
    assert focus.remaining() == timedelta(minutes=40)
    clock.now += timedelta(minutes=5)
    assert await focus.stop_focus() == 15
    assert focus.minutes_on(clock.now) == 15


async def test_focus_completion_announces(tmp_path):
    _, focus, clock, spoken, *_ = rig(tmp_path)
    await focus.start_focus(1)
    clock.now += timedelta(minutes=1, seconds=1)
    for _ in range(30):
        if spoken:
            break
        await asyncio.sleep(0.1)
    assert spoken == ["집중 1분이 끝났어요. 잠깐 쉬었다 해요."] and not focus.active


async def test_focus_and_nap_voice(tmp_path):
    _, focus, clock, spoken, *_ = rig(tmp_path)
    c = ctx(21, 0)
    assert (await focus.handle("집중 모드 50분 시작해줘", "집중모드50분시작해줘", c)).startswith("50분 집중 모드를 시작할게요")
    assert (await focus.handle("집중 모드 끝", "집중모드끝", c)).startswith("집중 모드를 끝냈어요")
    assert await focus.handle("오늘 얼마나 공부했어?", "오늘얼마나공부했어", c) == "오늘은 0분 집중했어요."
    reply = await focus.handle("30분만 잘게", "30분만잘게", c)
    assert reply.startswith("30분 동안 졸음 감지를 끌게요") and focus.napping
    assert await focus.handle("오늘 저녁 뭐 먹지", "오늘저녁뭐먹지", c) is None


async def test_nap_ends_with_wake_call(tmp_path):
    _, focus, clock, spoken, *_ = rig(tmp_path)
    woke = []
    focus.on_nap_end.append(lambda: woke.append(True))
    await focus.start_nap(1)
    clock.now += timedelta(minutes=1, seconds=1)
    for _ in range(30):
        if spoken:
            break
        await asyncio.sleep(0.1)
    assert spoken == ["낮잠 시간이 끝났어요. 일어나실 시간이에요."] and woke == [True]


async def test_return_after_absence_greets_and_pauses_focus(tmp_path):
    vision, focus, clock, spoken, events, presence, announcer = rig(tmp_path)
    vision.greet_after_sec = 600
    await vision.observe(obs(0))
    assert spoken[0].startswith("좋은 저녁이에요, 재원님. 오늘 일정은 1개예요.")
    await focus.start_focus(50)
    announcer.missed.append("지금은 빨래 할 차례예요.")
    for t in range(1, 30):
        await vision.observe(obs(t, owner=False))
    assert presence.state == "away" and focus.session["paused_at"] is not None
    await vision.observe(obs(700))
    assert presence.state == "present" and focus.session["paused_at"] is None
    assert spoken[-1] == "돌아오셨네요, 재원님. 40분 뒤에 UMC 스터디 일정이 있고, 새 메일이 3통 있어요. 자리 비운 사이에 알림이 1개 있었어요."


async def test_short_absence_no_greeting_and_stranger_state(tmp_path):
    vision, _, _, spoken, _, presence, _ = rig(tmp_path)
    vision.greet_after_sec = 600
    await vision.observe(obs(0))
    for t in range(1, 25):
        await vision.observe(obs(t, owner=False))
    await vision.observe(obs(60))
    assert len(spoken) == 1  # only the arrival greeting
    await vision.observe(obs(61, owner=False, stranger=True))
    await vision.observe(obs(62.5, owner=False, stranger=True))
    assert presence.state == "stranger"


async def test_drowsiness_alerts_and_nap_suppression(tmp_path):
    vision, focus, clock, spoken, events, *_ = rig(tmp_path)
    vision.monitor.baseline_ear = 0.3
    await vision.observe(obs(0))
    t = 1.0
    while t < 9:
        await vision.observe(obs(t, ear=0.05))
        t += 0.25
    alerts = [e.payload for e in events if e.type == "alert" and e.payload.get("active")]
    assert [a["level"] for a in alerts] == [1, 2]
    assert spoken[-2:] == ["재원님, 졸고 계신 것 같아요.", "재원님! 일어나세요!"]
    await vision.observe(obs(9.5))
    assert events[-2].payload.get("active") is False or any(
        e.type == "alert" and e.payload.get("active") is False for e in events[-4:]
    )

    await focus.start_nap(30)
    before = len(spoken)
    vision.monitor._cooldown_until = 0
    t = 100.0
    while t < 110:
        await vision.observe(obs(t, ear=0.05))
        t += 0.25
    assert len(spoken) == before  # napping: no drowsiness alerts


async def test_drowsiness_inactive_outside_hours(tmp_path):
    vision, focus, clock, spoken, *_ = rig(tmp_path, now=datetime(2026, 9, 29, 4, 0, tzinfo=KST))
    assert not vision.drowsiness_active()
    await focus.start_focus(50)  # focus mode turns it on at any hour
    assert vision.drowsiness_active()
