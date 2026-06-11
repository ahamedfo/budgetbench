"""Aggregations the dashboard needs: cost by department, spend vs. budget,
TCO projection, cost-per-passing-task, and PA write-back.

All money is USD pulled from runs.usd_cost (computed from tokens × public
list price by the pricing layer). A "task" is one run_id; an agent's run is
one (run_id, tool) row.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict

from src.pa.client import PlanningAnalyticsClient, get_pa_client
from src.storage import db as storage_db
from src.storage import orgs


# period helper: runs.started_at is ISO-8601, so substr(1,7) = "YYYY-MM".
_PERIOD_EXPR = "substr(started_at, 1, 7)"


def _verify_passed(verification_json: str | None) -> bool:
    if not verification_json:
        return False
    try:
        v = json.loads(verification_json)
    except (TypeError, ValueError):
        return False
    return bool(v.get("verify_sh_passed")) or (
        (v.get("tests_total") or 0) > 0 and (v.get("tests_failed") or 0) == 0
    )


def cost_by_department(conn: sqlite3.Connection) -> list[dict]:
    """Per department: total USD, run/task counts, and a per-agent breakdown."""
    depts = {d["id"]: d for d in orgs.list_departments(conn)}
    rows = conn.execute(
        """
        SELECT department_id, tool,
               SUM(usd_cost)            AS usd,
               COUNT(*)                 AS agent_runs,
               COUNT(DISTINCT run_id)   AS tasks
        FROM runs
        WHERE department_id IS NOT NULL
        GROUP BY department_id, tool
        """
    ).fetchall()

    by_dept: dict[int, dict] = {}
    for r in rows:
        did = r["department_id"]
        d = by_dept.setdefault(did, {
            "department_id": did,
            "department": depts.get(did, {}).get("name", f"#{did}"),
            "pa_dimension_key": depts.get(did, {}).get("pa_dimension_key"),
            "total_usd": 0.0,
            "by_tool": {},
        })
        d["by_tool"][r["tool"]] = {
            "usd": round(r["usd"] or 0.0, 6),
            "agent_runs": r["agent_runs"],
            "tasks": r["tasks"],
        }
        d["total_usd"] = round(d["total_usd"] + (r["usd"] or 0.0), 6)
    return list(by_dept.values())


def cost_per_passing_task(conn: sqlite3.Connection) -> list[dict]:
    """Per agent: avg USD per task and avg USD per *passing* task — the
    BOB-favorable hero metric (cheap output that fails isn't a bargain)."""
    rows = conn.execute(
        "SELECT tool, usd_cost, verification_json FROM runs"
    ).fetchall()
    agg: dict[str, dict] = defaultdict(lambda: {"usd": 0.0, "n": 0, "pass_usd": 0.0, "pass_n": 0})
    for r in rows:
        a = agg[r["tool"]]
        a["usd"] += r["usd_cost"] or 0.0
        a["n"] += 1
        if _verify_passed(r["verification_json"]):
            a["pass_usd"] += r["usd_cost"] or 0.0
            a["pass_n"] += 1
    out = []
    for tool, a in agg.items():
        out.append({
            "tool": tool,
            "tasks": a["n"],
            "passing_tasks": a["pass_n"],
            "avg_usd_per_task": round(a["usd"] / a["n"], 6) if a["n"] else None,
            "avg_usd_per_passing_task": round(a["pass_usd"] / a["pass_n"], 6) if a["pass_n"] else None,
            "pass_rate": round(a["pass_n"] / a["n"], 4) if a["n"] else None,
        })
    return sorted(out, key=lambda x: x["tool"])


def spend_vs_budget(conn: sqlite3.Connection, period: str,
                    pa_client: PlanningAnalyticsClient | None = None) -> list[dict]:
    """Per department for a period: budget (from PA), spend (from runs),
    remaining, and utilization %."""
    pa_client = pa_client or get_pa_client()
    budgets_by_key = pa_client.read_budgets(period)  # {pa_key: usd}
    depts = orgs.list_departments(conn)

    spend_rows = conn.execute(
        f"""
        SELECT department_id, SUM(usd_cost) AS usd, COUNT(DISTINCT run_id) AS tasks
        FROM runs
        WHERE department_id IS NOT NULL AND {_PERIOD_EXPR} = ?
        GROUP BY department_id
        """,
        (period,),
    ).fetchall()
    spend_by_dept = {r["department_id"]: (r["usd"] or 0.0, r["tasks"]) for r in spend_rows}

    out = []
    for d in depts:
        key = d.get("pa_dimension_key")
        budget = budgets_by_key.get(key) if key else None
        spend, tasks = spend_by_dept.get(d["id"], (0.0, 0))
        remaining = (budget - spend) if budget is not None else None
        util = (spend / budget) if budget else None
        out.append({
            "department_id": d["id"],
            "department": d["name"],
            "pa_dimension_key": key,
            "period": period,
            "budget_usd": budget,
            "spend_usd": round(spend, 6),
            "tasks": tasks,
            "remaining_usd": round(remaining, 6) if remaining is not None else None,
            "utilization": round(util, 4) if util is not None else None,
            "over_budget": (budget is not None and spend > budget),
        })
    return out


def tco_projection(conn: sqlite3.Connection) -> list[dict]:
    """Annualized cost per agent, overall and per department.

    Projection basis: observed average monthly spend × 12, where months are
    the distinct YYYY-MM periods that have runs. Clearly an extrapolation —
    the dashboard labels it as such.
    """
    rows = conn.execute(
        f"""
        SELECT tool, department_id, {_PERIOD_EXPR} AS period,
               SUM(usd_cost) AS usd
        FROM runs
        GROUP BY tool, department_id, period
        """
    ).fetchall()

    # tool -> {months:set, usd:float}; and (tool,dept) -> same
    by_tool: dict[str, dict] = defaultdict(lambda: {"months": set(), "usd": 0.0})
    by_tool_dept: dict[tuple, dict] = defaultdict(lambda: {"months": set(), "usd": 0.0})
    for r in rows:
        by_tool[r["tool"]]["months"].add(r["period"])
        by_tool[r["tool"]]["usd"] += r["usd"] or 0.0
        key = (r["tool"], r["department_id"])
        by_tool_dept[key]["months"].add(r["period"])
        by_tool_dept[key]["usd"] += r["usd"] or 0.0

    depts = {d["id"]: d["name"] for d in orgs.list_departments(conn)}

    def project(usd: float, months: set) -> float:
        n = max(len(months), 1)
        return round((usd / n) * 12, 2)

    tools = []
    for tool, a in by_tool.items():
        tools.append({
            "tool": tool,
            "observed_usd": round(a["usd"], 6),
            "observed_months": len(a["months"]),
            "projected_annual_usd": project(a["usd"], a["months"]),
        })

    per_dept = []
    for (tool, did), a in by_tool_dept.items():
        per_dept.append({
            "tool": tool,
            "department_id": did,
            "department": depts.get(did, f"#{did}" if did is not None else "unassigned"),
            "observed_usd": round(a["usd"], 6),
            "projected_annual_usd": project(a["usd"], a["months"]),
        })

    return [{
        "basis": "avg monthly spend × 12 (extrapolation)",
        "by_tool": sorted(tools, key=lambda x: x["tool"]),
        "by_tool_department": sorted(per_dept, key=lambda x: (x["tool"], str(x["department"]))),
    }]


def cost_timeline(conn: sqlite3.Connection) -> list[dict]:
    """Spend per (period, tool) for trend charts."""
    rows = conn.execute(
        f"""
        SELECT {_PERIOD_EXPR} AS period, tool, SUM(usd_cost) AS usd,
               COUNT(DISTINCT run_id) AS tasks
        FROM runs GROUP BY period, tool ORDER BY period
        """
    ).fetchall()
    return [dict(r) for r in rows]


def agent_efficiency(conn: sqlite3.Connection) -> list[dict]:
    """Per-agent operations metrics: time/task, tokens/task, token mix, $/task,
    and tokens-per-dollar (efficiency). Uses agent-reported duration where
    present, else wall-clock."""
    rows = conn.execute(
        """
        SELECT tool,
               AVG(COALESCE(duration_ms, wall_clock_ms)) AS dur_ms,
               AVG(input_tokens)  AS in_tok,
               AVG(output_tokens) AS out_tok,
               AVG(cached_tokens) AS cached_tok,
               AVG(usd_cost)      AS cost,
               COUNT(*)           AS n
        FROM runs GROUP BY tool
        """
    ).fetchall()
    out = []
    for r in rows:
        avg_in = r["in_tok"] or 0
        avg_out = r["out_tok"] or 0
        avg_cost = r["cost"] or 0
        total_tok = avg_in + avg_out
        out.append({
            "tool": r["tool"],
            "tasks": r["n"],
            "avg_duration_ms": round(r["dur_ms"] or 0),
            "avg_input_tokens": round(avg_in),
            "avg_output_tokens": round(avg_out),
            "avg_cached_tokens": round(r["cached_tok"] or 0),
            "avg_tokens_per_task": round(total_tok),
            "avg_usd_per_task": round(avg_cost, 6),
            "tokens_per_dollar": round(total_tok / avg_cost) if avg_cost else None,
        })
    return sorted(out, key=lambda x: x["tool"])


def department_detail(conn: sqlite3.Connection, department_id: int) -> dict:
    """Drill-down for one department: per-agent measured spend, and a
    breakdown by task type (mapped from the scenario's objective type)."""
    dept = orgs.get_department(conn, department_id)
    if not dept:
        return {}

    # Map scenario_id → human title + objective type (from disk metadata).
    from src.orchestrator import list_scenarios
    smeta = {s["id"]: s for s in list_scenarios()}

    by_tool = conn.execute(
        """
        SELECT tool, SUM(usd_cost) usd, COUNT(*) n,
               AVG(COALESCE(duration_ms, wall_clock_ms)) dur
        FROM runs WHERE department_id = ? GROUP BY tool
        """,
        (department_id,),
    ).fetchall()

    by_type_rows = conn.execute(
        """
        SELECT scenario_id, SUM(usd_cost) usd, COUNT(*) n
        FROM runs WHERE department_id = ? GROUP BY scenario_id
        """,
        (department_id,),
    ).fetchall()
    by_type: dict[str, dict] = {}
    for r in by_type_rows:
        meta = smeta.get(r["scenario_id"], {})
        ttype = (meta.get("objective_type") or "task").title()
        slot = by_type.setdefault(ttype, {"task_type": ttype, "usd": 0.0, "tasks": 0, "scenarios": []})
        slot["usd"] = round(slot["usd"] + (r["usd"] or 0.0), 6)
        slot["tasks"] += r["n"]
        slot["scenarios"].append(meta.get("title", r["scenario_id"]))

    return {
        "department": dept["name"],
        "department_id": dept["id"],
        "pa_dimension_key": dept.get("pa_dimension_key"),
        "monthly_task_volume": dept.get("monthly_task_volume"),
        "by_tool": [
            {"tool": r["tool"], "usd": round(r["usd"] or 0.0, 6), "tasks": r["n"],
             "avg_duration_ms": round(r["dur"] or 0)}
            for r in by_tool
        ],
        "by_task_type": list(by_type.values()),
    }


def record_run_actuals(payload: dict, pa_client: PlanningAnalyticsClient | None = None) -> dict | None:
    """Write a completed run's realized spend back to Planning Analytics as
    actuals, against the run's department + period. No-op if the run has no
    department. Returns the write summary or None."""
    department_id = payload.get("department_id")
    if not department_id:
        return None
    pa_client = pa_client or get_pa_client()
    conn = storage_db.connect()
    try:
        dept = orgs.get_department(conn, department_id)
    finally:
        conn.close()
    if not dept or not dept.get("pa_dimension_key"):
        return None

    period = (payload.get("started_at") or "")[:7]  # YYYY-MM
    total_usd = sum((t.get("usd_cost") or 0.0) for t in payload.get("tools", []))
    new_total = pa_client.write_actuals(dept["pa_dimension_key"], period, total_usd)
    return {
        "pa_dimension_key": dept["pa_dimension_key"],
        "period": period,
        "posted_usd": round(total_usd, 6),
        "running_actual_usd": new_total,
    }
