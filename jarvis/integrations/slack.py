"""Slack (read-only, user token): recent DMs to me and @mentions."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx2

from jarvis.integrations.oauth import AuthRequired

log = logging.getLogger(__name__)

API = "https://slack.com/api"
WINDOW_SEC = 24 * 3600
MAX_IMS = 30


def clean(text: str) -> str:
    text = re.sub(r"<@[A-Z0-9]+(\|[^>]+)?>", "@", text)
    text = re.sub(r"<(https?://[^|>]+)(\|([^>]+))?>", lambda m: m.group(3) or "링크", text)
    return re.sub(r"\s+", " ", text).strip()[:160]


class SlackSource:
    name = "slack"

    def __init__(self, token: str, http: httpx2.AsyncClient) -> None:
        self.token = token
        self.http = http
        self.user_id: str | None = None
        self._names: dict[str, str] = {}

    async def _call(self, method: str, **params: Any) -> dict[str, Any]:
        resp = await self.http.get(f"{API}/{method}", params=params, headers={"Authorization": f"Bearer {self.token}"})
        if resp.status_code == 429:
            raise httpx2.HTTPStatusError("rate limited", request=resp.request, response=resp)
        data = resp.json()
        if not data.get("ok"):
            error = data.get("error", "unknown")
            if error in ("invalid_auth", "not_authed", "token_revoked", "account_inactive", "missing_scope"):
                raise AuthRequired(error)
            raise httpx2.HTTPStatusError(f"slack {method}: {error}", request=resp.request, response=resp)
        return data

    async def _name(self, user: str) -> str:
        if user not in self._names:
            try:
                info = await self._call("users.info", user=user)
                profile = info["user"].get("profile", {})
                self._names[user] = profile.get("display_name") or info["user"].get("real_name") or info["user"]["name"]
            except (httpx2.HTTPError, KeyError, AuthRequired):
                self._names[user] = "알 수 없음"
        return self._names[user]

    async def fetch(self) -> dict[str, Any]:
        if self.user_id is None:
            self.user_id = (await self._call("auth.test"))["user_id"]
        oldest = time.time() - WINDOW_SEC
        items: list[dict[str, Any]] = []

        ims = (await self._call("conversations.list", types="im", limit=MAX_IMS)).get("channels", [])
        for im in ims[:MAX_IMS]:
            if im.get("user") == self.user_id:
                continue
            history = await self._call("conversations.history", channel=im["id"], oldest=f"{oldest:.0f}", limit=3)
            for msg in history.get("messages", []):
                if msg.get("user") and msg["user"] != self.user_id and not msg.get("subtype"):
                    items.append(await self._item(msg, "DM", f"{im['id']}:{msg['ts']}"))

        found = await self._call("search.messages", query=f"<@{self.user_id}>", sort="timestamp", count=10)
        for msg in found.get("messages", {}).get("matches", []):
            if float(msg.get("ts", 0)) < oldest or msg.get("user") == self.user_id:
                continue
            channel = msg.get("channel", {}).get("name")
            items.append(await self._item(msg, f"#{channel}" if channel else "멘션", f"m:{msg.get('iid') or msg['ts']}"))

        items.sort(key=lambda i: i["received_at"], reverse=True)
        return {"count": len(items), "items": items}

    async def _item(self, msg: dict[str, Any], where: str, item_id: str) -> dict[str, Any]:
        sender = msg.get("username") or await self._name(msg.get("user", ""))
        received = datetime.fromtimestamp(float(msg["ts"]), timezone.utc)
        return {
            "id": item_id,
            "sender": sender,
            "subject": where,
            "snippet": clean(msg.get("text", "")),
            "received_at": received.isoformat(timespec="seconds"),
        }
