"""Executive summary: project each department's *own* measured task cost to
org/annual scale.

Each department runs a different representative task, so cost-per-task differs
by (department, agent). We measure that from runs and project:
    dept monthly = dept.units[agent] × dept.volume
summed across departments. Recommended agent = cheapest org-wide; baseline =
most expensive. The frontend re-projects client-side per selected agent.
"""
from __future__ import annotations

import sqlite3

from src.pa.client import PlanningAnalyticsClient, get_pa_client
from src.storage import orgs

TOOLS = ("bob", "claude", "copilot")


def _dept_unit_costs(conn: sqlite3.Connection) -> dict[int, dict[str, float]]:
    """{department_id: {tool: avg usd per task}} from recorded runs."""
    rows = conn.execute(
        """
        SELECT department_id, tool, AVG(usd_cost) AS unit
        FROM runs WHERE department_id IS NOT NULL
        GROUP BY department_id, tool
        """
    ).fetchall()
    out: dict[int, dict[str, float]] = {}
    for r in rows:
        out.setdefault(r["department_id"], {})[r["tool"]] = r["unit"] or 0.0
    return out


def _org_tool_avg(dept_units: dict[int, dict[str, float]]) -> dict[str, float]:
    """Fallback unit cost per tool = mean across departments that have it."""
    avg = {}
    for t in TOOLS:
        vals = [u[t] for u in dept_units.values() if u.get(t)]
        if vals:
            avg[t] = sum(vals) / len(vals)
    return avg


def executive_summary(conn: sqlite3.Connection, period: str,
                      pa_client: PlanningAnalyticsClient | None = None) -> dict:
    pa_client = pa_client or get_pa_client()
    depts = orgs.list_departments(conn)
    budgets = pa_client.read_budgets(period)
    dept_units = _dept_unit_costs(conn)
    org_avg = _org_tool_avg(dept_units)

    # Scenario (task) metadata for each department.
    from src.orchestrator import list_scenarios
    smeta = {s["id"]: s for s in list_scenarios()}

    tools_present = [t for t in TOOLS if t in org_avg] or list(TOOLS)

    # Per-department record with a per-agent unit-cost map.
    dept_records = []
    for d in depts:
        did = d["id"]
        vol = d.get("monthly_task_volume") or 0
        budget = budgets.get(d.get("pa_dimension_key"), 0.0)
        units = {}
        for t in tools_present:
            units[t] = (dept_units.get(did, {}).get(t)) or org_avg.get(t, 0.0)
        meta = smeta.get(d.get("scenario_id"), {})
        dept_records.append({
            "department": d["name"],
            "department_id": did,
            "pa_dimension_key": d.get("pa_dimension_key"),
            "budget_usd": round(budget, 2),
            "volume": vol,
            "scenario_id": d.get("scenario_id"),
            "scenario_title": meta.get("title"),
            "scenario_description": meta.get("description"),
            "scenario_type": meta.get("objective_type"),
            "units": {t: round(units[t], 6) for t in units},
        })

    total_volume = sum(r["volume"] for r in dept_records)
    total_budget = sum(r["budget_usd"] for r in dept_records)

    # Org monthly projection per agent (sum of dept unit × volume).
    org_monthly = {t: sum(r["units"].get(t, 0.0) * r["volume"] for r in dept_records) for t in tools_present}
    recommended = min(org_monthly, key=org_monthly.get) if org_monthly else None
    baseline = max(org_monthly, key=org_monthly.get) if org_monthly else None

    agents = []
    for t in sorted(tools_present, key=lambda x: org_monthly.get(x, 0)):
        agents.append({
            "tool": t,
            "unit_usd": round(org_monthly[t] / total_volume, 6) if total_volume else 0.0,
            "projected_monthly_usd": round(org_monthly[t], 2),
            "projected_annual_usd": round(org_monthly[t] * 12, 2),
            "recommended": t == recommended,
        })

    return {
        "period": period,
        "recommended_agent": recommended,
        "baseline_agent": baseline,
        "total_budget_usd": round(total_budget, 2),
        "monthly_task_volume": total_volume,
        "departments": dept_records,
        "agents": agents,
    }
