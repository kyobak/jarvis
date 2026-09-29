"""FastAPI app: WebSocket event stream, static UI, OAuth callback placeholders."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from jarvis.core.app import JarvisApp
from jarvis.core.config import REPO_ROOT
from jarvis.core.event_bus import WILDCARD, Event

log = logging.getLogger(__name__)

UI_DIST = REPO_ROOT / "ui" / "dist"
# High-frequency events that may be dropped when a client falls behind.
LOSSY_TYPES = {"level", "drowsiness"}
CLIENT_QUEUE_MAX = 256

_PLACEHOLDER = """<!doctype html><html lang="ko"><meta charset="utf-8">
<title>Jarvis</title><body style="background:#030A12;color:#D6F4FF;font-family:sans-serif;padding:48px">
<h1>{title}</h1><p>{body}</p></body></html>"""


def create_app(jarvis: JarvisApp, ui_dist: Path = UI_DIST) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await jarvis.start()
        try:
            yield
        finally:
            await jarvis.stop()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.jarvis = jarvis

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True, "mock": jarvis.mock}

    @app.get("/api/snapshot")
    async def snapshot() -> JSONResponse:
        return JSONResponse([e.to_wire() for e in jarvis.store.snapshot()])

    def require_tool_token(authorization: str | None) -> None:
        expected = f"Bearer {jarvis.tool_token}"
        if not authorization or not secrets.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="bad token")

    # Tool endpoints for the Claude Code MCP bridge (loopback + per-run token).
    @app.get("/api/tools")
    async def list_tools(authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
        require_tool_token(authorization)
        return jarvis.tools.describe()

    @app.post("/api/tools/{name}")
    async def call_tool(
        name: str,
        body: dict[str, Any] = Body(default_factory=dict),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_tool_token(authorization)
        content, is_error = await jarvis.tools.call(name, body.get("arguments") or {})
        return {"content": content, "is_error": is_error}

    names = {"google": "Google (캘린더·Gmail)", "spotify": "Spotify", "slack": "Slack"}
    setup_hint = {
        "google": "Google Cloud에서 받은 OAuth 클라이언트 JSON을 "
        "<code>~/Library/Application Support/Jarvis/google_client_secret.json</code> 에 저장한 뒤 자비스를 다시 시작하세요.",
        "spotify": "<code>.env</code>에 <code>SPOTIFY_CLIENT_ID</code>를 넣고 자비스를 다시 시작하세요.",
        "slack": "Slack은 브라우저 연결 대신 <code>.env</code>의 <code>SLACK_USER_TOKEN</code>으로 연결해요.",
    }

    @app.get("/auth/{provider}", response_model=None)
    async def auth(provider: str) -> HTMLResponse | RedirectResponse:
        client = jarvis.oauth.get(provider)
        name = names.get(provider, provider)
        if client is None:
            hint = setup_hint.get(provider, "알 수 없는 연동이에요.")
            return HTMLResponse(_PLACEHOLDER.format(title=f"{name} 연결 준비가 필요해요", body=f"{hint}<br>자세한 순서는 docs/setup.md 에 있어요."))
        return RedirectResponse(client.authorize_url())

    @app.get("/callback/{provider}", response_class=HTMLResponse)
    async def callback(provider: str, code: str = "", state: str = "", error: str = "") -> str:
        client = jarvis.oauth.get(provider)
        name = names.get(provider, provider)
        if client is None:
            raise HTTPException(status_code=404)
        if error or not code:
            return _PLACEHOLDER.format(title=f"{name} 연결이 취소됐어요", body=f"사유: {html.escape(error or '코드 없음')}. 다시 시도해 주세요.")
        try:
            await client.exchange(code, state)
        except Exception as e:  # show a readable page instead of a stack trace
            log.warning("oauth %s failed: %s", provider, e)
            return _PLACEHOLDER.format(title=f"{name} 연결에 실패했어요", body="잠시 후 자비스 화면의 '다시 연결'을 다시 눌러 주세요.")
        await jarvis.oauth_connected(provider)
        return _PLACEHOLDER.format(title=f"{name} 연결 완료", body="이 창은 닫아도 돼요. 자비스 화면이 곧 새 정보로 바뀌어요.")

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        await socket.accept()
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=CLIENT_QUEUE_MAX)

        def enqueue(event: Event) -> None:
            if queue.full():
                if event.type in LOSSY_TYPES:
                    return
                queue.get_nowait()  # drop the oldest to keep the stream live
            queue.put_nowait(event)

        for event in jarvis.store.snapshot():
            enqueue(event)
        unsubscribe = jarvis.bus.subscribe(WILDCARD, enqueue)

        async def sender() -> None:
            while True:
                event = await queue.get()
                await socket.send_text(json.dumps(event.to_wire(), ensure_ascii=False))

        send_task = asyncio.create_task(sender())
        try:
            while True:
                raw = await socket.receive_text()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict):
                    await jarvis.handle_client(message)
        except WebSocketDisconnect:
            pass
        finally:
            unsubscribe()
            send_task.cancel()

    if (ui_dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=ui_dist, html=True), name="ui")
    else:

        @app.get("/", response_class=HTMLResponse)
        async def no_ui() -> str:
            return _PLACEHOLDER.format(
                title="UI가 아직 빌드되지 않았어요",
                body="<code>cd ui &amp;&amp; npm install &amp;&amp; npm run build</code> 를 실행한 뒤 다시 시작하세요.",
            )

    return app
