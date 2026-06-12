# BudgetBench — Architecture

One page covering how the system works, what it stores, and how it connects to IBM Planning Analytics. Built on Swayam's bakeoff engine (`bob-agents-battle`) as the roadmap, then extended.

## The three components

```
┌────────────────────────────┐      ┌──────────────────┐      ┌──────────────────────┐
│ ① RUN SYSTEM               │      │ ② DATA STORE     │      │ ③ PA CONNECTOR       │
│ Next.js UI (:3000)         │ ───▶ │ SQLite           │ ───▶ │ Planning Analytics   │
│ FastAPI orchestrator(:8000)│      │ backend/runs/    │      │ (mock now, TM1 REST  │
│ launches 3 CLIs in parallel│      │ runs.db          │      │  later) — does ALL   │
│ & captures their output    │      │ one row per      │      │  projections/models  │
│                            │      │ (run, agent)     │      │                      │
└────────────────────────────┘      └──────────────────┘      └──────────────────────┘
```

The web app's job is **run → collect → store**. Projections (cost over 1/3/6 months, 10/50 users) are **Planning Analytics' job** — the dashboard's "Projection Preview" band only previews what PA will model from the stored data.

## Data flow (one button press)

1. UI `POST /api/run` `{scenario_id, department_id, run_mode, submitter}` → FastAPI (`backend/src/server.py`).
2. Orchestrator (`backend/src/orchestrator.py`) **stages an isolated working-copy** of the scenario repo per agent (`stage_working_copy`) so Bob/Claude/Copilot can't interfere with each other.
3. **All three CLIs launch simultaneously** via `asyncio.gather`, each as an async subprocess (`runners/base.py`):
   - `bob "<prompt>" -y --chat-mode advanced --output-format stream-json`
   - `claude -p "<prompt>" --output-format stream-json --verbose --dangerously-skip-permissions`
   - `copilot -p "<prompt>" --yolo --no-remote --disable-builtin-mcps --output-format json`
4. Each agent's stdout (JSONL) is **streamed line-by-line** to the browser over SSE (`/api/stream/{run_id}/{tool}`) for the live view, and saved to `runs/<run_id>/<tool>/stdout.log`.
5. When an agent finishes, its **parser** (`parsers/{bob,claude,copilot}_parser.py`) extracts the key data from its own output format:
   - **tokens** (input / output / cached), **model**, **duration**, **native cost** (Bob → bobcoins, Claude → USD, Copilot → premium requests + tokens)
6. The **pricing calculator** (`pricing/calculator.py` + `rates.yaml`) normalizes native cost to **USD** using public list prices.
7. **Verification** (`scoring/objective_verifier.py`) runs the scenario's test suite (pytest) + semgrep + `verify.sh` against the agent's working copy → deterministic pass/fail.
8. The row is **inserted into SQLite** (`storage/db.py`) and realized spend is **written back to Planning Analytics as actuals** (`pa/` adapter; mock today).

## Run modes

| Mode | Behavior |
|---|---|
| `live` (default) | Each agent runs its **real CLI** if installed; agents without a CLI auto-fall back to a recording. Rows are badged ●LIVE / recorded. Today: Claude live; Bob & Copilot recorded until their CLIs are installed. |
| `simulated` | Re-streams bundled recordings through the same parse→price→store pipeline (free, deterministic — demo-safe). |
| `replay` | Re-streams a previous run's captured stdout. |

**Run ×N**: the UI can chain N runs (1/3/5/10/20) to build per-scenario averages — the dataset PA models. (A backend job queue is the future home for unattended 20× batches.)

## What we store (SQLite `runs` table — one row per agent per run)

| Field | Notes |
|---|---|
| `run_id`, `started_at`, `completed_at` | run identity + timing |
| `scenario_id`, `department_id`, `submitter` | what was run, for whom |
| `tool`, `model`, `run_mode` | which agent, which model, live/recorded |
| `input_tokens`, `output_tokens`, `cached_tokens` | token spend |
| `usd_cost`, `native_cost_value`, `native_cost_unit` | normalized + native cost |
| `duration_ms`, `wall_clock_ms`, `exit_code` | how long it took |
| `verification_json` | pytest/semgrep/verify.sh results (deterministic check) |
| `summary_json`, `extras_json`, `error` | agent self-report + diagnostics |

Aggregates: `GET /api/analytics/averages` (per scenario × agent: runs, avg USD, avg tokens, avg time, pass rate). Export: `GET /api/export/runs.csv` — the flat hand-off format for the PA connector.

## Planning Analytics connector (component ③)

Interface `PlanningAnalyticsClient` (`backend/src/pa/client.py`): `read_budgets(period)`, `read_actuals(period)`, `write_actuals(dept_key, period, usd)`. Today a JSON-file mock (`pa/mock_tm1.py`); swapping to a real TM1 REST client (TechZone instance) touches only this module. PA then models: avg cost/task × tasks/month × users × months.

## Lineage — built on Swayam's engine

| From his `bob-agents-battle` repo (ported) | Added on top |
|---|---|
| CLI runners + flags (`runners/`) | Next.js dashboard (live leaderboard, runs database) |
| JSONL parsers per agent (`parsers/`) | Departments (each owns one representative task/scenario) |
| Pricing rates + USD normalization (`pricing/`) | Recordings + hybrid live/fallback run modes |
| Deterministic verifier (`scoring/objective_verifier.py`) | SQLite attribution columns (department, submitter, run_mode) |
| Workspace isolation + parallel orchestration | PA adapter (mock TM1) + actuals write-back |
| SQLite storage approach | Aggregates API + CSV export + Run ×N batching |

## Session talking points

- **Framework**: FastAPI backend (async subprocess control + SSE streaming is natural in asyncio) + Next.js/React frontend (fast to build clean dashboards). Plain REST + SSE between them — no websockets, no queue, nothing exotic.
- **Database**: SQLite — zero-ops, file-based, lives next to the project (same choice as Swayam's engine), and trivially exportable to PA (CSV/REST).
- **Fields stored**: see table above — tokens, USD cost, time are the core three Swayam named; verification and attribution ride along.
- **Verification**: deferred per the call, but already implemented (Swayam's `objective_verifier.py`) and running — deterministic pytest/semgrep/regex checks per working copy.
- **Open questions**: TechZone PA instance access; unattended 20× batch runner (job queue); scenario library growth (RPG / Java / React domains); Bob & Copilot CLI access for live runs.

## Run it

```bash
./run.sh --setup   # once: deps + seed departments/budgets
./run.sh           # backend :8000 + frontend :3000
```
