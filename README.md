# BudgetBench

A local sales-enablement tool that runs the **same coding task across IBM BOB, Claude, and GitHub Copilot**, shows live token spend / time / cost per agent, verifies each with automated tests, rolls cost up **per department**, and compares it against budgets in **IBM Planning Analytics (TM1)**.

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

On the **Live Race** page: pick a scenario + department, hit **Launch task**, and watch the
three agents race — the leaderboard re-sorts as the cheapest *passing* agent wins, then a
banner shows the department's spend vs. its Planning Analytics budget. The **Dashboard** page
shows cost-per-passing-task, spend-vs-budget, and projected annual TCO.

## Run modes

| Mode | What it does | Needs |
|------|--------------|-------|
| `simulated` (default) | Re-streams bundled per-tool fixtures through the real pipeline → genuine recorded tokens/cost | nothing |
| `replay` | Re-streams a specific prior run's captured output | a prior run |
| `live` | Spawns the real `bob` / `claude` / `copilot` CLIs | those CLIs installed + authed |

Simulated/replay exist so demos never depend on a flaky live agent — they show **real recorded
economics** with zero CLIs installed.

## Layout

- `backend/` — FastAPI engine (ported from the bob-agents-battle reference, kept intact),
  plus the new department/budget layer (`src/storage/orgs.py`), Planning Analytics adapter
  (`src/pa/`), analytics roll-ups (`src/analytics/`), and the fixture-replay runner
  (`src/runners/simulated.py`).
- `frontend/` — Next.js 14 + Tailwind (IBM Carbon look) + Recharts dashboard.
- `backend/scenarios/` — task definitions (prompt + repo + tests + verify.sh).

## Status

Phases 0–2 complete (engine, simulated/replay, departments/budgets/PA mock, Live Race +
Dashboard). Next: author more department scenarios; wire real `bob`/`copilot` once memberships
exist; swap the PA mock for real TM1 REST. See the plan file for details.
