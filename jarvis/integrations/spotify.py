"""Spotify: playback through the desktop app via AppleScript (no Premium or OAuth needed),
search through the Web API (PKCE OAuth, optional)."""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Any

import httpx2

from jarvis.core.secrets import SecretStore
from jarvis.integrations.oauth import OAuthClient

log = logging.getLogger(__name__)

STATE_SCRIPT = """
if application "Spotify" is running then
  tell application "Spotify"
    set t to current track
    set sep to (ASCII character 9)
    return (player state as string) & sep & (name of t) & sep & (artist of t) & sep & (album of t) & sep & ¬
      (duration of t) & sep & (player position) & sep & (artwork url of t) & sep & (sound volume) & sep & (spotify url of t)
  end tell
else
  return "not_running"
end if
"""


async def osascript(script: str, timeout: float = 5.0) -> str:
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", script, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("osascript timed out")
    if proc.returncode != 0:
        raise RuntimeError(err.decode(errors="replace").strip()[:200])
    return out.decode(errors="replace").strip()


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def parse_state(raw: str) -> dict[str, Any] | None:
    if not raw or raw == "not_running":
        return None
    parts = raw.split("\t")
    if len(parts) < 9:
        return None
    state, title, artist, album, duration, position, art, volume, uri = parts[:9]

    def num(v: str) -> float:
        try:
            return float(v.replace(",", "."))  # some locales print 12,5
        except ValueError:
            return 0.0

    return {
        "title": title or None,
        "artist": artist,
        "album": album,
        "duration_ms": int(num(duration)),
        "progress_ms": int(num(position) * 1000),
        "art_url": art or None,
        "is_playing": state == "playing",
        "volume": int(num(volume)),
        "uri": uri,
    }


class AppleScriptSpotify:
    """Controls the local Spotify desktop app (asks for Automation permission once)."""

    name = "spotify"

    @staticmethod
    def available() -> bool:
        return shutil.which("osascript") is not None

    async def state(self) -> dict[str, Any] | None:
        return parse_state(await osascript(STATE_SCRIPT))

    async def _tell(self, command: str) -> None:
        await osascript(f'tell application "Spotify" to {command}')

    async def play(self) -> None:
        await self._tell("play")

    async def pause(self) -> None:
        await self._tell("pause")

    async def next(self) -> None:
        await self._tell("next track")

    async def previous(self) -> None:
        await self._tell("previous track")

    async def set_volume(self, volume: int) -> None:
        await self._tell(f"set sound volume to {max(0, min(100, int(volume)))}")

    async def play_uri(self, uri: str) -> None:
        await self._tell(f'play track "{_quote(uri)}"')


def make_spotify_oauth(client_id: str, secrets: SecretStore, http: httpx2.AsyncClient, redirect_uri: str) -> OAuthClient:
    return OAuthClient(
        name="spotify",
        auth_url="https://accounts.spotify.com/authorize",
        token_url="https://accounts.spotify.com/api/token",
        client_id=client_id,
        client_secret=None,  # PKCE public client: no secret on the device
        scopes=["playlist-read-private", "user-library-read"],
        redirect_uri=redirect_uri,
        secrets=secrets,
        http=http,
    )


class SpotifySearch:
    def __init__(self, oauth: OAuthClient) -> None:
        self.oauth = oauth

    async def find(self, query: str) -> dict[str, str] | None:
        """Best playlist (for moods/genres) or track for a spoken query."""
        data = await self.oauth.get_json(
            "https://api.spotify.com/v1/search",
            {"q": query, "type": "playlist,track", "limit": "5", "market": "from_token"},
        )
        playlists = [p for p in (data.get("playlists") or {}).get("items", []) if p]
        tracks = [t for t in (data.get("tracks") or {}).get("items", []) if t]
        if tracks and query.replace(" ", "").lower() in tracks[0]["name"].replace(" ", "").lower():
            t = tracks[0]
            return {"uri": t["uri"], "name": t["name"], "kind": "track"}
        if playlists:
            p = playlists[0]
            return {"uri": p["uri"], "name": p["name"], "kind": "playlist"}
        if tracks:
            t = tracks[0]
            return {"uri": t["uri"], "name": t["name"], "kind": "track"}
        return None
