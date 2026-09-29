import json
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest

from helpers import ctx
from jarvis.core.announcer import Announcer
from jarvis.core.config import Config
from jarvis.core.db import Database
from jarvis.core.event_bus import WILDCARD, EventBus
from jarvis.core.presence import Presence
from jarvis.core.secrets import SecretStore
from jarvis.core.settings import Settings
from jarvis.core.status import StatusBoard
from jarvis.core.timeutil import KST
from jarvis.integrations.google import GoogleCalendarSource, make_google_oauth
from jarvis.integrations.oauth import AuthRequired
from jarvis.skills.calendar import CalendarService

NOW = datetime(2026, 9, 29, 18, 30, tzinfo=KST)  # Tuesday


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Google:
    """Fake Google token + Calendar endpoints."""

    def __init__(self):
        self.token_requests = []
        self.refresh_ok = True
        self.calendar_down = False
        self.items = [
            {"id": "a", "summary": "UMC 스터디", "start": {"dateTime": "2026-09-29T19:00:00+09:00"}, "end": {"dateTime": "2026-09-29T20:30:00+09:00"}},
            {"id": "b", "summary": "과제 마감", "start": {"dateTime": "2026-09-29T23:00:00+09:00"}, "end": {"dateTime": "2026-09-29T23:00:00+09:00"}},
            {"id": "c", "summary": "개강 파티", "start": {"date": "2026-09-30"}, "end": {"date": "2026-10-01"}},
            {"id": "d", "summary": "알고리즘 강의", "start": {"dateTime": "2026-09-30T10:00:00+09:00"}, "end": {"dateTime": "2026-09-30T11:15:00+09:00"}},
            {"id": "x", "status": "cancelled", "summary": "취소됨", "start": {"dateTime": "2026-09-30T12:00:00+09:00"}},
        ]

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "oauth2.googleapis.com":
            form = parse_qs(request.content.decode())
            self.token_requests.append(form)
            if form["grant_type"] == ["refresh_token"] and not self.refresh_ok:
                return httpx2.Response(400, json={"error": "invalid_grant"})
            body = {"access_token": "at-1", "expires_in": 3600}
            if form["grant_type"] == ["authorization_code"]:
                body["refresh_token"] = "rt-1"
            return httpx2.Response(200, json=body)
        if self.calendar_down:
            raise httpx2.ConnectError("offline", request=request)
        assert request.headers["authorization"] == "Bearer at-1"
        return httpx2.Response(200, json={"items": self.items})


@pytest.fixture
def google(tmp_path):
    client_file = tmp_path / "client.json"
    client_file.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "cs"}}))
    fake = Google()
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(fake))
    oauth = make_google_oauth(client_file, SecretStore(None, use_keyring=False), http, "http://127.0.0.1:8765/callback/google")
    return fake, oauth


async def test_oauth_pkce_exchange_and_refresh(google):
    fake, oauth = google
    url = urlparse(oauth.authorize_url())
    q = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert q["code_challenge_method"] == ["S256"] and q["access_type"] == ["offline"]
    assert "calendar.readonly" in q["scope"][0] and "gmail.readonly" in q["scope"][0]
    with pytest.raises(AuthRequired):
        await oauth.exchange("code", "forged-state")
    await oauth.exchange("code-1", q["state"][0])
    sent = fake.token_requests[-1]
    assert sent["code_verifier"][0] and sent["redirect_uri"] == ["http://127.0.0.1:8765/callback/google"]
    assert oauth.has_token() and await oauth.access_token() == "at-1"

    oauth.invalidate_access()
    fake.refresh_ok = False
    with pytest.raises(AuthRequired):
        await oauth.access_token()
    assert not oauth.has_token()  # expired refresh token is dropped → UI shows "다시 연결"


def build(tmp_path, source=None, configured=True, clock=None):
    clock = clock or Clock(NOW)
    bus = EventBus()
    events = []
    bus.subscribe(WILDCARD, events.append)
    settings = Settings(bus, Config(), None)
    presence = Presence(bus)
    announcer = Announcer(bus, settings, presence, clock)
    spoken = []

    async def speaker(text, sound):
        spoken.append(text)

    announcer.speaker = speaker
    status = StatusBoard(bus)
    svc = CalendarService(Database(tmp_path / "j.db"), bus, status, announcer, presence, settings, clock, source, configured)
    return svc, clock, events, spoken, status, presence


async def connected_service(tmp_path, google, clock=None):
    fake, oauth = google
    q = parse_qs(urlparse(oauth.authorize_url()).query)
    await oauth.exchange("c", q["state"][0])
    svc, *rest = build(tmp_path, GoogleCalendarSource(oauth, ["primary"], KST), clock=clock)
    return (svc, *rest)


async def test_sync_normalises_and_caches(tmp_path, google):
    svc, clock, events, _, status, _ = await connected_service(tmp_path, google)
    assert await svc.sync()
    titles = [e["title"] for e in svc.events]
    assert titles == ["UMC 스터디", "과제 마감", "개강 파티", "알고리즘 강의"]
    assert svc.events[2]["all_day"] is True
    assert status.data["integrations"]["calendar"] == "ok"
    schedule = [e for e in events if e.type == "schedule"][-1].payload
    assert [e["title"] for e in schedule["events"]] == ["UMC 스터디", "과제 마감"]  # today only

    # Offline: keep showing the cache and say so.
    google[0].calendar_down = True
    svc.db.conn.commit()
    again, *_ = build(tmp_path, svc.source)
    again._load_cache()
    assert [e["title"] for e in again.events] == titles
    assert not await again.sync()
    assert again.offline and [e["title"] for e in again.events] == titles


async def test_expired_token_flags_reconnect(tmp_path, google):
    svc, _, _, _, status, _ = await connected_service(tmp_path, google)
    svc.source.oauth.invalidate_access()
    google[0].refresh_ok = False
    assert not await svc.sync()
    assert status.data["integrations"]["calendar"] == "expired" and svc.source is None


async def test_pre_and_start_alerts_once(tmp_path, google):
    svc, clock, _, spoken, _, _ = await connected_service(tmp_path, google)
    await svc.sync()
    await svc.check_alerts()  # 18:30: nothing within 10 min
    assert spoken == []
    clock.now = datetime(2026, 9, 29, 18, 50, tzinfo=KST)
    await svc.check_alerts()
    await svc.check_alerts()
    assert spoken == ["10분 뒤에 UMC 스터디 일정이 있어요."]
    clock.now = datetime(2026, 9, 29, 19, 0, 5, tzinfo=KST)
    await svc.check_alerts()
    assert spoken[-1] == "지금은 UMC 스터디 시간이에요." and len(spoken) == 2


async def test_running_event_at_startup_is_not_announced(tmp_path, google):
    svc, clock, _, spoken, _, _ = await connected_service(tmp_path, google, Clock(datetime(2026, 9, 29, 19, 1, tzinfo=KST)))
    await svc.sync()
    await svc.check_alerts()
    assert spoken == []


async def test_local_questions(tmp_path, google):
    svc, clock, *_ , presence = await connected_service(tmp_path, google)
    await svc.sync()
    c = ctx(18, 30)
    today = await svc.handle("오늘 일정 뭐야?", "오늘일정뭐야", c)
    assert today == "오늘 일정은 2개예요. 오후 7시 UMC 스터디, 오후 11시 과제 마감."
    tomorrow = await svc.handle("내일 오전에 뭐 있어?", "내일오전에뭐있어", c)
    assert tomorrow == "내일 오전 일정은 2개예요. 종일 개강 파티, 오전 10시 알고리즘 강의."
    assert await svc.handle("목요일 비어 있어?", "목요일비어있어", c) == "10월 1일 목요일은 비어 있어요."
    assert (await svc.handle("다음 일정 뭐야", "다음일정뭐야", c)).startswith("다음 일정은 오후 7시 UMC 스터디이고, 30분")
    await presence.set("stranger", c.now)
    assert "UMC" not in await svc.handle("오늘 일정 뭐야?", "오늘일정뭐야", c)
    assert await svc.handle("오늘 저녁 뭐 먹지", "오늘저녁뭐먹지", c) is None


async def test_not_connected_answer(tmp_path):
    svc, *_ = build(tmp_path, None, configured=False)
    assert "연결되지 않았어요" in await svc.handle("오늘 일정 뭐야", "오늘일정뭐야", ctx())


async def test_callback_route_end_to_end(tmp_path, monkeypatch, google):
    from fastapi.testclient import TestClient

    from jarvis.core.app import JarvisApp
    from jarvis.server.app import create_app

    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    app = JarvisApp(Config(), mock=False, db_path=str(tmp_path / "a.db"), voice="mock")
    app.oauth["google"] = google[1]
    connected = []

    async def fake_connected(name):
        connected.append(name)

    app.oauth_connected = fake_connected
    with TestClient(create_app(app, ui_dist=tmp_path)) as client:
        r = client.get("/auth/google", follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"].startswith("https://accounts.google.com/")
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        ok = client.get(f"/callback/google?code=abc&state={state}")
        assert "연결 완료" in ok.text and connected == ["google"]
        assert "취소" in client.get("/callback/google?error=access_denied").text
