"""CRUD for departments and budgets.

Departments are the unit of cost attribution and the bridge to Planning
Analytics: each carries a `pa_dimension_key` (a TM1 dimension element) so
realized agent spend can be written back to the right cube coordinate.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------- Departments ----------------

def create_department(
    conn: sqlite3.Connection,
    name: str,
    pa_dimension_key: str | None = None,
    description: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO departments (name, pa_dimension_key, description, created_at) "
        "VALUES (?, ?, ?, ?)",
        (name, pa_dimension_key, description, _now()),
    )
    conn.commit()
    return cur.lastrowid


def upsert_department(
    conn: sqlite3.Connection,
    name: str,
    pa_dimension_key: str | None = None,
    description: str | None = None,
    monthly_task_volume: int | None = None,
    scenario_id: str | None = None,
) -> int:
    """Create the department if absent, else update its fields.
    Returns the department id. Idempotent — safe for seeding."""
    row = conn.execute("SELECT id FROM departments WHERE name = ?", (name,)).fetchone()
    if row:
        conn.execute(
            "UPDATE departments SET pa_dimension_key = COALESCE(?, pa_dimension_key), "
            "description = COALESCE(?, description), "
            "monthly_task_volume = COALESCE(?, monthly_task_volume), "
            "scenario_id = COALESCE(?, scenario_id) WHERE id = ?",
            (pa_dimension_key, description, monthly_task_volume, scenario_id, row["id"]),
        )
        conn.commit()
        return row["id"]
    dept_id = create_department(conn, name, pa_dimension_key, description)
    conn.execute(
        "UPDATE departments SET monthly_task_volume = COALESCE(?, monthly_task_volume), "
        "scenario_id = COALESCE(?, scenario_id) WHERE id = ?",
        (monthly_task_volume, scenario_id, dept_id),
    )
    conn.commit()
    return dept_id


def list_departments(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM departments ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def get_department(conn: sqlite3.Connection, department_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM departments WHERE id = ?", (department_id,)).fetchone()
    return dict(r) if r else None


# ---------------- Budgets ----------------

def set_budget(
    conn: sqlite3.Connection,
    department_id: int,
    period: str,
    amount_usd: float,
    source: str = "manual",
) -> int:
    """Insert or replace the budget for (department, period)."""
    cur = conn.execute(
        "INSERT INTO budgets (department_id, period, amount_usd, source) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(department_id, period) DO UPDATE SET "
        "amount_usd = excluded.amount_usd, source = excluded.source",
        (department_id, period, amount_usd, source),
    )
    conn.commit()
    return cur.lastrowid


def get_budget(conn: sqlite3.Connection, department_id: int, period: str) -> dict | None:
    r = conn.execute(
        "SELECT * FROM budgets WHERE department_id = ? AND period = ?",
        (department_id, period),
    ).fetchone()
    return dict(r) if r else None


def list_budgets(conn: sqlite3.Connection, period: str | None = None) -> list[dict]:
    if period:
        rows = conn.execute("SELECT * FROM budgets WHERE period = ?", (period,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM budgets").fetchall()
    return [dict(r) for r in rows]
