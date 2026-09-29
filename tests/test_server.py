from fastapi.testclient import TestClient

from jarvis.core.app import JarvisApp
from jarvis.core.config import Config
from jarvis.server.app import create_app


def receive_until(ws, type_, limit=200):
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == type_:
            return msg
    raise AssertionError(f"no {type_} event")


def test_ws_replays_snapshot_in_mock_mode(mock_app, tmp_path):
    with TestClient(create_app(mock_app, ui_dist=tmp_path)) as client:
        with client.websocket_connect("/ws") as ws:
            types = {ws.receive_json()["type"] for _ in range(8)}
    assert {"status", "state", "schedule", "reminders", "messages", "now_playing", "focus"} <= types


def test_dev_state_switch_is_broadcast(mock_app, tmp_path):
    with TestClient(create_app(mock_app, ui_dist=tmp_path)) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "dev", "payload": {"action": "state", "value": "thinking"}})
            msg = receive_until(ws, "state")
            while msg["payload"]["core"] != "thinking":
                msg = receive_until(ws, "state")
    assert msg["payload"]["core"] == "thinking"


def test_dev_commands_ignored_outside_dev_mode(tmp_path):
    app = JarvisApp(Config(), mock=False, db_path=str(tmp_path / "j.db"))
    with TestClient(create_app(app, ui_dist=tmp_path)) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "dev", "payload": {"action": "state", "value": "alert"}})
        assert app.store.get("state") == {"core": "idle"}
        status = app.store.get("status")
    assert status["mock"] is False
    assert status["integrations"]["gmail"] == "disabled"


def test_placeholder_when_ui_not_built(mock_app, tmp_path):
    with TestClient(create_app(mock_app, ui_dist=tmp_path)) as client:
        r = client.get("/")
        assert r.status_code == 200 and "npm run build" in r.text
        assert client.get("/api/health").json() == {"ok": True, "mock": True}
        assert "준비 중" in client.get("/auth/google").text
