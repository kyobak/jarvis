from datetime import date

from jarvis.core.db import MIGRATIONS, Database


def test_schema_created_and_versioned(tmp_path):
    db = Database(tmp_path / "j.db")
    tables = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"reminders", "events_cache", "messages_cache", "focus_sessions", "presence_log", "llm_usage"} <= tables
    assert db.schema_version == len(MIGRATIONS)
    db.close()
    # Reopening must not re-run migrations.
    assert Database(tmp_path / "j.db").schema_version == len(MIGRATIONS)


def test_llm_usage_accumulates():
    db = Database(":memory:")
    d = date(2026, 9, 29)
    db.record_llm_usage(d, 100, 20)
    db.record_llm_usage(d, 50, 5)
    assert db.llm_usage(d) == {"calls": 2, "input_tokens": 150, "output_tokens": 25}
    assert db.llm_usage(date(2026, 9, 30))["calls"] == 0
