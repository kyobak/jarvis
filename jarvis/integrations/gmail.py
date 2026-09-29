"""Gmail (read-only): unread mail in the Primary inbox, metadata and snippet only."""

from __future__ import annotations

import email.utils
from datetime import datetime, timezone
from typing import Any

from jarvis.integrations.google import GMAIL_API
from jarvis.integrations.oauth import OAuthClient

QUERY = "is:unread in:inbox category:primary"


def sender_name(from_header: str) -> str:
    name, addr = email.utils.parseaddr(from_header)
    return name or addr.split("@")[0] or "알 수 없음"


class GmailSource:
    name = "gmail"

    def __init__(self, oauth: OAuthClient) -> None:
        self.oauth = oauth
        self._meta: dict[str, dict[str, Any]] = {}  # id → item (metadata is immutable)

    async def fetch(self, limit: int = 8) -> dict[str, Any]:
        listing = await self.oauth.get_json(f"{GMAIL_API}/messages", {"q": QUERY, "maxResults": str(limit)})
        ids = [m["id"] for m in listing.get("messages", [])]
        items = []
        for mid in ids:
            if mid not in self._meta:
                msg = await self.oauth.get_json(
                    f"{GMAIL_API}/messages/{mid}",
                    {"format": "metadata", "metadataHeaders": ["From", "Subject"]},
                )
                headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
                received = datetime.fromtimestamp(int(msg.get("internalDate", "0")) / 1000, timezone.utc)
                self._meta[mid] = {
                    "id": mid,
                    "sender": sender_name(headers.get("from", "")),
                    "subject": headers.get("subject", "(제목 없음)"),
                    "snippet": msg.get("snippet", "")[:160],
                    "received_at": received.isoformat(timespec="seconds"),
                }
            items.append(self._meta[mid])
        self._meta = {k: v for k, v in self._meta.items() if k in ids}
        count = max(len(ids), int(listing.get("resultSizeEstimate", 0) or 0))
        return {"count": count, "items": items}
