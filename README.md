# BudgetBench

Run the **same coding task across IBM BOB, Claude, and GitHub Copilot** — launch all three CLIs simultaneously in isolated workspaces, capture each agent's output in real time, extract **token count / time / cost in USD**, and **store every run in SQLite**. That database is the dataset **IBM Planning Analytics** ingests to model long-term cost projections; the dashboard shows the live race, the runs database, and a preview of what PA will model.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design (components, data flow, schema, PA connector).

```
┌───────────────┐     SSE      ┌──────────────────────────┐
│ Next.js (3000)│ ◀──────────▶ │ FastAPI engine (8000)    │
│ Live Race +   │   REST       │  runners · parsers ·     │
│ Dashboard     │ ◀──────────▶ │  pricing · verifier · DB │
└───────────────┘              │  Planning Analytics mock │
                               └──────────────────────────┘
```

## Quick start

```bash
./run.sh --setup     # once: venv + deps + seed demo departments/budgets
./run.sh             # start backend (:8000) + frontend (:3000)
# open http://localhost:3000
```

One page: pick a **department** (each owns one representative task — e.g. Security → SQL
injection fix, Finance → payroll tax bug), hit **Run this task**, and watch the three agents
race. Every run lands in the **Runs Database** (per-scenario averages + raw runs + CSV export)
— the dataset Planning Analytics ingests. Below it, the **Projection Preview** band previews
the modeling that moves to PA.

## Run modes

| Mode | What it does | Needs |
|------|--------------|-------|
| `live` (default) | Spawns each agent's real CLI if installed (today: `claude`); others auto-fall back to recordings, badged accordingly | `claude` (and later `bob`/`copilot`) installed + authed |
| `simulated` | Re-streams bundled per-tool recordings through the real pipeline → genuine recorded tokens/cost | nothing |
| `replay` | Re-streams a specific prior run's captured output | a prior run |

Use **Runs ×N** to batch a scenario (3/5/10/20 runs) and build the per-scenario averages that
Planning Analytics models. Export the database anytime via the **Export CSV** button
(`/api/export/runs.csv`).

## Layout

- `backend/` — FastAPI engine (ported from the bob-agents-battle reference, kept intact),
  plus the new department/budget layer (`src/storage/orgs.py`), Planning Analytics adapter
  (`src/pa/`), analytics roll-ups (`src/analytics/`), and the fixture-replay runner
  (`src/runners/simulated.py`).
- `frontend/` — Next.js 14 + Tailwind (IBM Carbon look) + Recharts dashboard.
- `backend/scenarios/` — task definitions (prompt + repo + tests + verify.sh).

## Status

V1 (run → collect → store) complete: parallel CLI launch with workspace isolation, real-time
output capture, token/time/USD extraction, SQLite storage, averages + CSV export, live Claude
runs with deterministic verification (pytest/semgrep), and the Planning Analytics mock with
actuals write-back. Next: Bob/Copilot live CLIs; swap the PA mock for a real TM1 (TechZone)
instance; grow the scenario library (RPG / Java / React domains).
