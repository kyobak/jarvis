import json
import socket
import subprocess
import sys
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from jarvis.brain.mcp_bridge import handle
from jarvis.core.app import JarvisApp
from jarvis.core.config import Config
from jarvis.server.app import create_app


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    app = JarvisApp(Config(), mock=True, db_path=str(tmp_path / "j.db"), enable_voice=False)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(app, ui_dist=tmp_path), port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield app, f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


def run_bridge(url, token, messages):
    proc = subprocess.run(
        [sys.executable, "-m", "jarvis.brain.mcp_bridge"],
        input="".join(json.dumps(m) + "\n" for m in messages),
        capture_output=True,
        text=True,
        timeout=30,
        env={"JARVIS_TOOLS_URL": url, "JARVIS_TOOLS_TOKEN": token, "PATH": "/usr/bin:/bin"},
    )
    return [json.loads(line) for line in proc.stdout.splitlines()]


def test_bridge_end_to_end(live_server):
    app, url = live_server
    out = run_bridge(
        url,
        app.tool_token,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_status", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "nope"},
        ],
    )
    assert [m["id"] for m in out] == [1, 2, 3, 4]  # the notification got no reply
    assert out[0]["result"]["protocolVersion"] == "2025-06-18"
    tools = out[1]["result"]["tools"]
    names = [t["name"] for t in tools]
    assert names[0] == "get_status" and "create_reminder" in names
    assert tools[0]["inputSchema"]["additionalProperties"] is False
    call = out[2]["result"]
    assert call["isError"] is False
    assert json.loads(call["content"][0]["text"])["camera"] == "모의"
    assert out[3]["error"]["code"] == -32601


def test_bridge_with_wrong_token_fails_closed(live_server):
    _, url = live_server
    out = run_bridge(url, "wrong", [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
    assert "error" in out[0]


def test_tool_routes_require_token(mock_app, tmp_path):
    with TestClient(create_app(mock_app, ui_dist=tmp_path)) as client:
        assert client.get("/api/tools").status_code == 401
        assert client.post("/api/tools/get_status", headers={"Authorization": "Bearer x"}).status_code == 401
        ok = client.get("/api/tools", headers={"Authorization": f"Bearer {mock_app.tool_token}"})
        assert ok.status_code == 200 and ok.json()[0]["name"] == "get_status"


def test_unknown_protocol_version_falls_back():
    reply = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999"}}, None)
    assert reply["result"]["protocolVersion"] == "2025-06-18"
