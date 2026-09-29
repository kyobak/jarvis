"""OAuth 2.0 authorization-code flow with PKCE and a loopback redirect to Jarvis's own
server (http://127.0.0.1:8765/callback/<provider>). Used for Google and Spotify."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx2

from jarvis.core.secrets import SecretStore

log = logging.getLogger(__name__)


class AuthRequired(Exception):
    """No usable token: the user must (re)connect in the browser."""


@dataclass
class OAuthClient:
    name: str  # google | spotify
    auth_url: str
    token_url: str
    client_id: str
    client_secret: str | None
    scopes: list[str]
    redirect_uri: str
    secrets: SecretStore
    http: httpx2.AsyncClient
    extra_auth_params: dict[str, str] = field(default_factory=dict)
    _pending: dict[str, tuple[str, float]] = field(default_factory=dict)  # state -> (verifier, created)
    _access: tuple[str, float] | None = None  # (token, expires_at)

    @property
    def token_key(self) -> str:
        return f"{self.name}_refresh_token"

    def has_token(self) -> bool:
        return bool(self.secrets.get(self.token_key))

    def authorize_url(self) -> str:
        verifier = secrets.token_urlsafe(64)[:96]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(24)
        now = time.monotonic()
        self._pending = {s: v for s, v in self._pending.items() if now - v[1] < 600}
        self._pending[state] = (verifier, now)
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.scopes),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            **self.extra_auth_params,
        }
        return f"{self.auth_url}?{urlencode(params)}"

    async def _token_request(self, data: dict[str, str]) -> dict:
        data = {**data, "client_id": self.client_id}
        if self.client_secret:
            data["client_secret"] = self.client_secret
        resp = await self.http.post(self.token_url, data=data)
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code != 200:
            error = body.get("error", resp.status_code)
            log.warning("%s token request failed: %s", self.name, error)
            if error in ("invalid_grant", "invalid_client", "unauthorized_client"):
                raise AuthRequired(str(error))
            raise httpx2.HTTPStatusError(f"token endpoint {resp.status_code}", request=resp.request, response=resp)
        return body

    async def exchange(self, code: str, state: str) -> None:
        pending = self._pending.pop(state, None)
        if pending is None:
            raise AuthRequired("unknown or expired state")
        body = await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "code_verifier": pending[0],
            }
        )
        refresh = body.get("refresh_token")
        if not refresh:
            raise AuthRequired("no refresh token returned")
        self.secrets.set(self.token_key, refresh)
        self._remember(body)
        log.info("%s connected", self.name)

    def _remember(self, body: dict) -> None:
        token = body.get("access_token")
        if token:
            self._access = (token, time.monotonic() + int(body.get("expires_in", 3600)) - 60)

    async def access_token(self) -> str:
        if self._access and self._access[1] > time.monotonic():
            return self._access[0]
        refresh = self.secrets.get(self.token_key)
        if not refresh:
            raise AuthRequired("not connected")
        try:
            body = await self._token_request({"grant_type": "refresh_token", "refresh_token": refresh})
        except AuthRequired:
            # e.g. Google "testing" apps expire refresh tokens after 7 days.
            self.secrets.delete(self.token_key)
            self._access = None
            raise
        if body.get("refresh_token"):  # Spotify may rotate it
            self.secrets.set(self.token_key, body["refresh_token"])
        self._remember(body)
        return self._access[0]

    def invalidate_access(self) -> None:
        self._access = None

    async def get_json(self, url: str, params: dict | None = None) -> dict:
        """GET with a bearer token; retries once after refreshing on 401."""
        for attempt in range(2):
            token = await self.access_token()
            resp = await self.http.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 401 and attempt == 0:
                self.invalidate_access()
                continue
            if resp.status_code == 401:
                raise AuthRequired("unauthorized")
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        raise AuthRequired("unauthorized")


def load_google_client(path) -> tuple[str, str] | None:
    """(client_id, client_secret) from a downloaded Desktop-app OAuth client JSON."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    block = data.get("installed") or data.get("web") or {}
    if not block.get("client_id"):
        return None
    return block["client_id"], block.get("client_secret", "")
