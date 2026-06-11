"""Local JSON-backed stand-in for a TM1 cube.

Stores Budget and Actual versions of an AI-cost cube in a single JSON file
so the dashboard's spend-vs-budget and write-back flows work end-to-end
before a real Planning Analytics instance exists. Shape:

    {
      "budgets": { "ENGINEERING": { "2026-06": 5000.0 }, ... },
      "actuals": { "ENGINEERING": { "2026-06": 123.45 }, ... }
    }
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CUBE_PATH = Path(
    os.environ.get("PA_MOCK_CUBE_PATH", str(PROJECT_ROOT / "runs" / "pa_cube.json"))
)


class MockTM1Client:
    """Implements PlanningAnalyticsClient against a JSON file."""

    def __init__(self, cube_path: Path | str = DEFAULT_CUBE_PATH):
        self.cube_path = Path(cube_path)
        self._lock = Lock()
        self.cube_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.cube_path.exists():
            self._write({"budgets": {}, "actuals": {}})

    # ---- internal ----
    def _read(self) -> dict:
        try:
            return json.loads(self.cube_path.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            return {"budgets": {}, "actuals": {}}

    def _write(self, data: dict) -> None:
        self.cube_path.write_text(json.dumps(data, indent=2, sort_keys=True))

    # ---- interface ----
    def read_budgets(self, period: str) -> dict[str, float]:
        data = self._read()
        return {
            key: periods[period]
            for key, periods in data.get("budgets", {}).items()
            if period in periods
        }

    def read_actuals(self, period: str) -> dict[str, float]:
        data = self._read()
        return {
            key: periods[period]
            for key, periods in data.get("actuals", {}).items()
            if period in periods
        }

    def write_actuals(self, pa_key: str, period: str, amount_usd: float) -> float:
        """Add to the Actual cell for (pa_key, period). Returns new total."""
        with self._lock:
            data = self._read()
            actuals = data.setdefault("actuals", {})
            cell = actuals.setdefault(pa_key, {})
            cell[period] = round(cell.get(period, 0.0) + float(amount_usd), 6)
            self._write(data)
            return cell[period]

    # ---- seeding helper (mock-only; not part of the interface) ----
    def set_budget(self, pa_key: str, period: str, amount_usd: float) -> None:
        with self._lock:
            data = self._read()
            budgets = data.setdefault("budgets", {})
            budgets.setdefault(pa_key, {})[period] = float(amount_usd)
            self._write(data)
