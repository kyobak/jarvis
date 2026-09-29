"""SQLite storage. Schema is versioned with PRAGMA user_version."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    when_utc TEXT NOT NULL,
    repeat_rule TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE TABLE IF NOT EXISTS events_cache (
    id TEXT PRIMARY KEY,
    calendar_id TEXT NOT NULL,
    title TEXT NOT NULL,
    start_utc TEXT NOT NULL,
    end_utc TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages_cache (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    sender TEXT,
    subject TEXT,
    snippet TEXT,
    received_at TEXT NOT NULL,
    seen INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS focus_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_utc TEXT NOT NULL,
    end_utc TEXT,
    planned_min INTEGER,
    actual_min INTEGER,
    paused_sec INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS presence_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL CHECK (event IN ('arrived', 'left', 'drowsy')),
    at_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_usage (
    date TEXT PRIMARY KEY,
    calls INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0
);
"""

SCHEMA_V2 = """
ALTER TABLE events_cache ADD COLUMN all_day INTEGER NOT NULL DEFAULT 0;
"""

MIGRATIONS = [SCHEMA_V1, SCHEMA_V2]


class Database:
    def __init__(self, path: Path | str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
            with self.conn:
                self.conn.executescript(script)
                self.conn.execute(f"PRAGMA user_version = {i}")

    @property
    def schema_version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    def record_llm_usage(self, day: date, input_tokens: int, output_tokens: int) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO llm_usage (date, calls, input_tokens, output_tokens)
                VALUES (?, 1, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    calls = calls + 1,
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens
                """,
                (day.isoformat(), input_tokens, output_tokens),
            )

    def llm_usage(self, day: date) -> dict[str, int]:
        row = self.conn.execute(
            "SELECT calls, input_tokens, output_tokens FROM llm_usage WHERE date = ?",
            (day.isoformat(),),
        ).fetchone()
        if row is None:
            return {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        return dict(row)

    def close(self) -> None:
        self.conn.close()
