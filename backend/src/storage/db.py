from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.models.run_result import RunResult


DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "runs" / "runs.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    tool            TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    wall_clock_ms   INTEGER,
    exit_code       INTEGER,
    model           TEXT,
    native_cost_value REAL,
    native_cost_unit TEXT,
    usd_cost        REAL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cached_tokens   INTEGER,
    summary_json    TEXT,
    verification_json TEXT,
    extras_json     TEXT,
    error           TEXT,
    -- Attribution + provenance (added for the dashboard layer)
    run_mode        TEXT,            -- live | replay | simulated
    department_id   INTEGER,         -- FK → departments.id (nullable)
    submitter       TEXT             -- who launched this task
);

CREATE INDEX IF NOT EXISTS idx_runs_run_id ON runs(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_scenario ON runs(scenario_id);
CREATE INDEX IF NOT EXISTS idx_runs_tool ON runs(tool);
CREATE INDEX IF NOT EXISTS idx_runs_department ON runs(department_id);

-- Departments are first-class: each maps to a Planning Analytics (TM1)
-- dimension element via pa_dimension_key, so spend can be written back as
-- actuals against the right cube coordinate.
CREATE TABLE IF NOT EXISTS departments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL UNIQUE,
    pa_dimension_key TEXT,            -- TM1 element name (e.g. "ENGINEERING")
    description      TEXT,
    created_at       TEXT,
    -- Expected AI-assisted coding tasks per month for this department.
    -- Drives the long-term projection (measured cost/task × volume).
    monthly_task_volume INTEGER DEFAULT 0,
    -- The one representative task (scenario) this department runs.
    scenario_id      TEXT
);

-- A department's AI-agent budget for a period. source distinguishes a
-- figure pulled from Planning Analytics vs. one entered by hand.
CREATE TABLE IF NOT EXISTS budgets (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id    INTEGER NOT NULL,
    period           TEXT NOT NULL,   -- e.g. "2026-06", "2026-Q2", "FY2026"
    amount_usd       REAL NOT NULL,
    source           TEXT,            -- planning_analytics | manual
    UNIQUE(department_id, period),
    FOREIGN KEY (department_id) REFERENCES departments(id)
);
"""

# Columns added after the original schema shipped. On an existing DB the
# CREATE TABLE IF NOT EXISTS above is a no-op, so we additively ALTER in
# any missing columns here.
_MIGRATIONS = [
    ("run_mode", "TEXT"),
    ("department_id", "INTEGER"),
    ("submitter", "TEXT"),
    ("duration_ms", "INTEGER"),  # agent-reported task time (vs. wall_clock_ms)
]


_DEPT_MIGRATIONS = [
    ("monthly_task_volume", "INTEGER DEFAULT 0"),
    ("scenario_id", "TEXT"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
    for col, coltype in _MIGRATIONS:
        if col not in existing:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {coltype}")
    dept_cols = {r["name"] for r in conn.execute("PRAGMA table_info(departments)").fetchall()}
    for col, coltype in _DEPT_MIGRATIONS:
        if col not in dept_cols:
            conn.execute(f"ALTER TABLE departments ADD COLUMN {col} {coltype}")
    conn.commit()


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def save_run(
    conn: sqlite3.Connection,
    run_id: str,
    result: RunResult,
    run_mode: str | None = None,
    department_id: int | None = None,
    submitter: str | None = None,
) -> int:
    duration_ms = (result.extras or {}).get("duration_ms")
    cur = conn.execute(
        """
        INSERT INTO runs (
            run_id, scenario_id, tool, started_at, completed_at, wall_clock_ms,
            exit_code, model, native_cost_value, native_cost_unit, usd_cost,
            input_tokens, output_tokens, cached_tokens,
            summary_json, verification_json, extras_json, error,
            run_mode, department_id, submitter, duration_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            result.scenario_id,
            result.tool,
            result.started_at.isoformat(),
            result.completed_at.isoformat() if result.completed_at else None,
            result.wall_clock_ms,
            result.exit_code,
            result.model,
            result.native_cost_value,
            result.native_cost_unit,
            result.usd_cost,
            result.input_tokens,
            result.output_tokens,
            result.cached_tokens,
            json.dumps(result.summary.to_dict()) if result.summary else None,
            json.dumps(result.verification.to_dict()) if result.verification else None,
            json.dumps(result.extras) if result.extras else None,
            result.error,
            run_mode,
            department_id,
            submitter,
            duration_ms,
        ),
    )
    conn.commit()
    return cur.lastrowid


def list_runs(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_runs_for_run_id(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM runs WHERE run_id = ? ORDER BY tool", (run_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def delete_run(conn: sqlite3.Connection, run_id: str) -> int:
    """Delete all rows for a given run_id. Returns count deleted."""
    cur = conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
    conn.commit()
    return cur.rowcount


def delete_all_runs(conn: sqlite3.Connection) -> int:
    cur = conn.execute("DELETE FROM runs")
    conn.commit()
    return cur.rowcount
