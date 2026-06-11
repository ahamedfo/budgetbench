"""FastAPI server for the bake-off harness.

Pages:
  GET /                          → 3-column live view
  GET /runs                      → run history
  GET /run/{run_id}              → completed run report

JSON API:
  POST /api/run                  → start a run (body: {"scenario_id": "..."})
  GET  /api/run/{run_id}/status  → snapshot of current run state
  GET  /api/run/{run_id}/result  → final results (after completion)
  GET  /api/runs                 → list past runs
  GET  /api/scenarios            → list available scenarios

SSE:
  GET /api/stream/{run_id}/{tool}  → ndjson event stream from a single tool
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from src import orchestrator
from src.analytics import rollups
from src.display_labels import display_model_for_row
from src.pa.client import get_pa_client
from src.storage import db as storage_db
from src.storage import orgs


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = PROJECT_ROOT / "frontend" / "templates"
STATIC_DIR = PROJECT_ROOT / "frontend" / "static"


# -------- In-process run registry --------
# run_id → { "queues": {tool: asyncio.Queue}, "task": asyncio.Task,
#            "status": "running"|"complete"|"failed",
#            "result": dict | None, "scenario_id": str }
RUNS: dict[str, dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # On shutdown, cancel anything in flight
    for run in RUNS.values():
        t = run.get("task")
        if t and not t.done():
            t.cancel()


app = FastAPI(title="Bake-off Harness", lifespan=lifespan)

# Allow the Next.js dashboard (localhost:3000) to call the API + SSE directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _from_json(s):
    if not s:
        return {}
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return {}


def _thousand_sep(n):
    if n is None or n == "":
        return "—"
    try:
        return "{:,}".format(int(n))
    except (TypeError, ValueError):
        return str(n)


templates.env.filters["from_json"] = _from_json
templates.env.filters["thousand_sep"] = _thousand_sep
templates.env.globals["display_model_for_row"] = display_model_for_row


# ---------------- HTML pages ----------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    scenarios = orchestrator.list_scenarios()
    return templates.TemplateResponse(
        request, "index.html", {"scenarios": scenarios}
    )


@app.get("/run/{run_id}", response_class=HTMLResponse)
async def run_page(request: Request, run_id: str):
    conn = storage_db.connect()
    try:
        rows = storage_db.get_runs_for_run_id(conn, run_id)
    finally:
        conn.close()
    if not rows:
        rows = []
    # Look up the scenario's display title for the report header
    scenario = None
    scenario_id = rows[0]["scenario_id"] if rows else None
    if scenario_id:
        for s in orchestrator.list_scenarios():
            if s["id"] == scenario_id:
                scenario = s
                break
    return templates.TemplateResponse(
        request, "report.html",
        {"run_id": run_id, "rows": rows, "scenario": scenario},
    )


# ---------------- JSON API ----------------

@app.get("/api/scenarios")
async def api_scenarios():
    return orchestrator.list_scenarios()


@app.get("/api/agents/status")
async def api_agent_status():
    """Per-agent live readiness: which CLIs are installed so live mode can
    run them for real (vs. falling back to a recording)."""
    from src.runners.resolve import availability
    return availability()


@app.get("/api/runs")
async def api_runs():
    conn = storage_db.connect()
    try:
        return storage_db.list_runs(conn, limit=50)
    finally:
        conn.close()


@app.delete("/api/runs/{run_id}")
async def api_delete_run(run_id: str):
    """Delete a single run: SQLite rows + the runs/<id>/ directory on disk."""
    import shutil
    if "/" in run_id or ".." in run_id:
        raise HTTPException(400, "invalid run_id")
    conn = storage_db.connect()
    try:
        rows_deleted = storage_db.delete_run(conn, run_id)
    finally:
        conn.close()
    run_dir = orchestrator.RUNS_DIR / run_id
    folder_deleted = False
    if run_dir.exists() and run_dir.is_dir():
        shutil.rmtree(run_dir, ignore_errors=True)
        folder_deleted = True
    return {"run_id": run_id, "rows_deleted": rows_deleted, "folder_deleted": folder_deleted}


@app.delete("/api/runs")
async def api_delete_all_runs():
    """Wipe ALL past runs from DB + disk. Used by 'Delete all' in the UI."""
    import shutil
    conn = storage_db.connect()
    try:
        rows_deleted = storage_db.delete_all_runs(conn)
    finally:
        conn.close()
    folders_deleted = 0
    if orchestrator.RUNS_DIR.exists():
        for child in orchestrator.RUNS_DIR.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
                folders_deleted += 1
    return {"rows_deleted": rows_deleted, "folders_deleted": folders_deleted}


@app.post("/api/run")
async def api_run(payload: dict):
    scenario_id = payload.get("scenario_id")
    if not scenario_id:
        raise HTTPException(400, "scenario_id required")
    tools = payload.get("tools") or ["bob", "claude", "copilot"]
    # run_mode: live | replay | simulated. Default to simulated so the app
    # works out-of-the-box without the bob/copilot CLIs installed.
    run_mode = payload.get("run_mode") or orchestrator.SIMULATED
    department_id = payload.get("department_id")
    submitter = payload.get("submitter")

    queues = {t: asyncio.Queue() for t in tools}

    async def _run_then_capture():
        try:
            result = await orchestrator.run_bakeoff(
                scenario_id=scenario_id,
                tools=tools,
                queues=queues,
                run_mode=run_mode,
                department_id=department_id,
                submitter=submitter,
            )
            RUNS[run_id]["result"] = result
            RUNS[run_id]["status"] = "complete"
            # Write realized spend back to Planning Analytics as actuals.
            # Best-effort: a PA hiccup must never fail the run.
            try:
                writeback = rollups.record_run_actuals(result)
                if writeback:
                    RUNS[run_id]["pa_writeback"] = writeback
            except Exception as e:  # noqa: BLE001
                RUNS[run_id]["pa_writeback_error"] = str(e)
        except Exception as e:
            RUNS[run_id]["status"] = "failed"
            RUNS[run_id]["error"] = str(e)
            # Push sentinels so any stream readers can exit
            for q in queues.values():
                await q.put(None)

    task = asyncio.create_task(_run_then_capture())
    import uuid, os
    run_id = f"pending-{uuid.uuid4().hex[:12]}"
    RUNS[run_id] = {
        "queues": queues,
        "task": task,
        "status": "running",
        "result": None,
        "scenario_id": scenario_id,
        "tools": tools,
        "run_mode": run_mode,
    }
    # Surface env-driven display overrides so the UI can substitute the
    # *projected* model in places like Copilot's "Model: ..." stream line
    # (otherwise the audience sees the actual Haiku model, contradicting
    # the priced-as-Sonnet figure in the footer).
    display_overrides = {}
    proj = os.environ.get("COPILOT_DISPLAY_AS_MODEL")
    if proj:
        display_overrides["copilot"] = proj.strip()
    return {
        "run_id": run_id,
        "tools": tools,
        "scenario_id": scenario_id,
        "run_mode": run_mode,
        "display_overrides": display_overrides,
    }


@app.get("/api/run/{run_id}/status")
async def api_run_status(run_id: str):
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run_id")
    return {
        "run_id": run_id,
        "status": run["status"],
        "scenario_id": run["scenario_id"],
        "tools": run["tools"],
        "has_result": run.get("result") is not None,
    }


@app.get("/api/run/{run_id}/result")
async def api_run_result(run_id: str):
    run = RUNS.get(run_id)
    if run is None or run.get("result") is None:
        raise HTTPException(404, "not ready")
    return run["result"]


# ---------------- Departments & budgets ----------------

@app.get("/api/departments")
async def api_departments():
    conn = storage_db.connect()
    try:
        return orgs.list_departments(conn)
    finally:
        conn.close()


@app.post("/api/departments")
async def api_create_department(payload: dict):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    conn = storage_db.connect()
    try:
        dept_id = orgs.upsert_department(
            conn, name,
            pa_dimension_key=payload.get("pa_dimension_key"),
            description=payload.get("description"),
        )
        return orgs.get_department(conn, dept_id)
    finally:
        conn.close()


@app.get("/api/budgets")
async def api_budgets(period: str | None = None):
    conn = storage_db.connect()
    try:
        return orgs.list_budgets(conn, period=period)
    finally:
        conn.close()


@app.put("/api/budgets")
async def api_set_budget(payload: dict):
    try:
        dept_id = int(payload["department_id"])
        period = str(payload["period"])
        amount = float(payload["amount_usd"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "department_id, period, amount_usd required")
    source = payload.get("source", "manual")
    conn = storage_db.connect()
    try:
        orgs.set_budget(conn, dept_id, period, amount, source=source)
        # Mirror manual budgets into the PA mock so spend-vs-budget (which
        # reads budgets from PA) stays consistent.
        dept = orgs.get_department(conn, dept_id)
    finally:
        conn.close()
    if dept and dept.get("pa_dimension_key"):
        client = get_pa_client()
        if hasattr(client, "set_budget"):
            client.set_budget(dept["pa_dimension_key"], period, amount)
    return {"department_id": dept_id, "period": period, "amount_usd": amount, "source": source}


# ---------------- Analytics ----------------

@app.get("/api/analytics/cost-by-department")
async def api_cost_by_department():
    conn = storage_db.connect()
    try:
        return rollups.cost_by_department(conn)
    finally:
        conn.close()


@app.get("/api/analytics/cost-per-passing-task")
async def api_cost_per_passing_task():
    conn = storage_db.connect()
    try:
        return rollups.cost_per_passing_task(conn)
    finally:
        conn.close()


@app.get("/api/analytics/spend-vs-budget")
async def api_spend_vs_budget(period: str):
    conn = storage_db.connect()
    try:
        return rollups.spend_vs_budget(conn, period)
    finally:
        conn.close()


@app.get("/api/analytics/tco-projection")
async def api_tco_projection():
    conn = storage_db.connect()
    try:
        return rollups.tco_projection(conn)
    finally:
        conn.close()


@app.get("/api/analytics/cost-timeline")
async def api_cost_timeline():
    conn = storage_db.connect()
    try:
        return rollups.cost_timeline(conn)
    finally:
        conn.close()


@app.get("/api/analytics/efficiency")
async def api_efficiency():
    conn = storage_db.connect()
    try:
        return rollups.agent_efficiency(conn)
    finally:
        conn.close()


@app.get("/api/analytics/department/{department_id}")
async def api_department_detail(department_id: int):
    conn = storage_db.connect()
    try:
        return rollups.department_detail(conn, department_id)
    finally:
        conn.close()


@app.get("/api/analytics/executive")
async def api_executive(period: str):
    from src.analytics.executive import executive_summary
    conn = storage_db.connect()
    try:
        return executive_summary(conn, period)
    finally:
        conn.close()


@app.get("/api/stream/{run_id}/{tool}")
async def api_stream(run_id: str, tool: str, request: Request):
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run_id")
    q = run["queues"].get(tool)
    if q is None:
        raise HTTPException(404, f"no queue for tool {tool}")

    async def event_gen():
        while True:
            if await request.is_disconnected():
                return
            try:
                item = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": ""}
                continue

            # Per-tool `_done` marker carries the fully-processed row
            # (cost, tokens, summary, verification, display_model). The
            # orchestrator emits this the moment the tool finishes,
            # without waiting on the other tools.
            if isinstance(item, dict) and item.get("_done"):
                yield {"event": "done", "data": json.dumps(item["row"], default=str)}
                return

            if item is None:
                # Legacy / safety: stream ended without a processed row
                yield {"event": "done", "data": "{}"}
                return

            yield {"event": "stdout", "data": item.rstrip("\n")}

    return EventSourceResponse(event_gen())
