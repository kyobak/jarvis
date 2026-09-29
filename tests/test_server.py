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


def test_dev_commands_ignored_outside_dev_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    app = JarvisApp(Config(), mock=False, db_path=str(tmp_path / "j.db"), voice="mock")
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


def _app(tmp_path, name, backend=None):
    cfg = Config()
    if backend:
        cfg.llm.backend = backend
    return JarvisApp(cfg, mock=False, db_path=str(tmp_path / f"{name}.db"), voice="mock")


def test_ai_backends_fall_back_to_off_without_key(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    for var in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    app = _app(tmp_path, "a")
    assert app.llm_backend_name == "openai_compat" and app.brain.backend.name == "off"
    assert _app(tmp_path, "b", "api").brain.backend.name == "off"

    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    backend = _app(tmp_path, "c").brain.backend
    assert backend.name == "openai_compat" and backend.label == "Gemini"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert _app(tmp_path, "d", "api").brain.backend.name == "api"


def test_status_reports_ai_label(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    app = _app(tmp_path, "e")
    with TestClient(create_app(app, ui_dist=tmp_path)):
        status = app.store.get("status")
    assert status["llm"]["label"] == "Gemini" and status["integrations"]["ai"] == "ok"
