"""Planning Analytics client contract + factory.

The interface intentionally mirrors how a TM1 cube is addressed so the real
implementation is a thin drop-in. Conceptually we read/write a cube like:

    [AICostCube].(Department, Period, Version, Measure=USD)

where Version ∈ {Budget, Actual}. `read_budgets` reads the Budget version;
`write_actuals` posts to the Actual version. A real client would issue TM1
REST cellset writes (POST /api/v1/Cubes('AICostCube')/tm1.Update or a
cellset PATCH); the mock just edits a local JSON file.
"""
from __future__ import annotations

import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class PlanningAnalyticsClient(Protocol):
    """Read budgets and write back realized agent spend as actuals.

    All amounts are USD. `pa_key` is a department's TM1 dimension element
    (departments.pa_dimension_key). `period` is a TM1 time element such as
    "2026-06", "2026-Q2", or "FY2026".
    """

    def read_budgets(self, period: str) -> dict[str, float]:
        """Return {pa_key: budgeted_usd} for the given period."""
        ...

    def read_actuals(self, period: str) -> dict[str, float]:
        """Return {pa_key: actual_usd_to_date} for the given period."""
        ...

    def write_actuals(self, pa_key: str, period: str, amount_usd: float) -> float:
        """Add `amount_usd` to the Actual cell for (pa_key, period).
        Returns the new running total. Idempotency is the caller's job."""
        ...


def get_pa_client() -> "PlanningAnalyticsClient":
    """Return the configured PA client.

    Today this is always the mock. When a real TM1 instance is provisioned,
    branch on an env var (e.g. PA_BACKEND=tm1) and return a real client that
    satisfies the same Protocol.
    """
    backend = os.environ.get("PA_BACKEND", "mock").lower()
    if backend == "mock":
        from src.pa.mock_tm1 import MockTM1Client
        return MockTM1Client()
    raise NotImplementedError(
        f"PA_BACKEND={backend!r} not wired yet. Implement a real TM1 client "
        "that satisfies PlanningAnalyticsClient and return it here."
    )
