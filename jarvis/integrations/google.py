"""Google Calendar + Gmail over REST (read-only scopes), sharing one OAuth client."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx2

from jarvis.core.secrets import SecretStore
from jarvis.integrations.oauth import OAuthClient, load_google_client

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


def make_google_oauth(
    client_file: Path, secrets: SecretStore, http: httpx2.AsyncClient, redirect_uri: str
) -> OAuthClient | None:
    creds = load_google_client(client_file)
    if creds is None:
        return None
    return OAuthClient(
        name="google",
        auth_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        client_id=creds[0],
        client_secret=creds[1],
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        secrets=secrets,
        http=http,
        # offline + consent: always return a refresh token.
        extra_auth_params={"access_type": "offline", "prompt": "consent"},
    )


def _parse_when(value: dict[str, str], tz: ZoneInfo) -> tuple[datetime, bool]:
    if "dateTime" in value:
        return datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00")).astimezone(tz), False
    d = date.fromisoformat(value["date"])
    return datetime(d.year, d.month, d.day, tzinfo=tz), True


class GoogleCalendarSource:
    def __init__(self, oauth: OAuthClient, calendar_ids: list[str], tz: ZoneInfo) -> None:
        self.oauth = oauth
        self.calendar_ids = calendar_ids
        self.tz = tz

    async def fetch(self, start: datetime, days: int = 8) -> list[dict[str, Any]]:
        end = start + timedelta(days=days)
        events: list[dict[str, Any]] = []
        for cal_id in self.calendar_ids:
            data = await self.oauth.get_json(
                f"{CALENDAR_API}/calendars/{quote(cal_id, safe='')}/events",
                {
                    "timeMin": start.isoformat(),
                    "timeMax": end.isoformat(),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": "250",
                },
            )
            for item in data.get("items", []):
                if item.get("status") == "cancelled" or "start" not in item:
                    continue
                s, all_day = _parse_when(item["start"], self.tz)
                e, _ = _parse_when(item.get("end", item["start"]), self.tz)
                events.append(
                    {
                        "id": f"{cal_id}:{item['id']}",
                        "title": item.get("summary") or "(제목 없음)",
                        "start": s,
                        "end": e,
                        "all_day": all_day,
                        "calendar": cal_id,
                    }
                )
        events.sort(key=lambda ev: ev["start"])
        return events
