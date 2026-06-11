"""Seed departments + budgets for the dashboard demo.

Idempotent: re-running updates in place. Writes departments/budgets to the
app DB and mirrors budgets into the Planning Analytics mock cube so
spend-vs-budget works immediately.

    python -m scripts.seed [PERIOD]   # PERIOD defaults to 2026-06
"""
from __future__ import annotations

import sys

from src.pa.client import get_pa_client
from src.storage import db as storage_db
from src.storage import orgs


# (name, pa_key, description, monthly_budget_usd, monthly_task_volume, scenario_id)
# Each department owns ONE representative task (scenario). Budgets + volumes
# are enterprise-scale so the long-term projection reads like a real dashboard.
DEPARTMENTS = [
    ("Engineering", "ENGINEERING", "Platform & legacy modernization", 28000.0, 22000, "02-eng-legacy-refactor"),
    ("Finance",     "FINANCE",     "Payroll, tax & reporting logic",  12000.0, 9000,  "03-fin-payroll-tax"),
    ("Security",    "SECURITY",    "Vulnerability remediation",       16000.0, 11000, "01-sqli-flask"),
    ("Data",        "DATA",        "ETL & data-quality fixes",        9000.0,  7000,  "04-data-etl-parse"),
]


def main(period: str = "2026-06") -> None:
    conn = storage_db.connect()
    pa = get_pa_client()
    try:
        for name, key, desc, budget, volume, scenario in DEPARTMENTS:
            dept_id = orgs.upsert_department(
                conn, name, pa_dimension_key=key, description=desc,
                monthly_task_volume=volume, scenario_id=scenario,
            )
            orgs.set_budget(conn, dept_id, period, budget, source="planning_analytics")
            if hasattr(pa, "set_budget"):
                pa.set_budget(key, period, budget)
            print(f"  dept #{dept_id:<2} {name:<12} task={scenario:<24} "
                  f"budget=${budget:,.0f} volume={volume:,}/mo")
    finally:
        conn.close()
    print(f"Seeded {len(DEPARTMENTS)} departments for {period}.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2026-06")
