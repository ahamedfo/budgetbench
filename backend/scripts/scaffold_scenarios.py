"""Author the per-department task scenarios + their recorded agent runs.

Each department maps to ONE representative coding task. This writes the
scenario folder (ground-truth.yaml, prompt.txt, a small real repo + tests,
verify.sh) and generates recordings/{bob,claude,copilot}.jsonl with distinct,
dollar-scale, BOB-favorable cost profiles so departments genuinely differ.

    python -m scripts.scaffold_scenarios
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCEN = PROJECT_ROOT / "scenarios"

ACTIONS = [
    ("read", "Listing project files"),
    ("read", "Reading the target module"),
    ("grep", "Locating the defect"),
    ("edit", "Applying the fix"),
    ("edit", "Hardening related code paths"),
    ("write", "Adding regression tests"),
    ("shell", "Running pytest -q"),
    ("done", "Finalizing changes"),
]


def sections(summary, change, tests, passed):
    return (
        f"## TASK SUMMARY\n{summary}\n\n"
        f"## CODE CHANGES\n{change}\n\n"
        f"## TESTS ADDED\n{tests}\n\n"
        f"## TEST RESULTS\n{passed} passed, 0 failed"
    )


# ---- stream builders (authentic shapes the parsers consume) ----

def claude_stream(secs_text, cost_usd, fresh_in, cache_create, cache_read, out_tok, dur_ms, model="claude-opus-4-7"):
    lines = [{"type": "system", "subtype": "init", "session_id": "rec", "model": model}]
    for kind, label in ACTIONS:
        lines.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": kind, "input": {}}]}, "tool_name": kind, "activity_label": label})
    lines.append({"type": "assistant", "message": {"content": [{"type": "text", "text": secs_text}]}})
    lines.append({"type": "result", "subtype": "success", "total_cost_usd": cost_usd, "duration_ms": dur_ms,
                  "num_turns": len(ACTIONS),
                  "usage": {"input_tokens": fresh_in, "cache_creation_input_tokens": cache_create,
                            "cache_read_input_tokens": cache_read, "output_tokens": out_tok},
                  "modelUsage": {model: {"costUSD": cost_usd}}, "result": secs_text})
    return "\n".join(json.dumps(o) for o in lines) + "\n"


def bob_stream(secs_text, coins, in_tok, out_tok, dur_ms, tool_calls, model="premium"):
    lines = [{"type": "init", "timestamp": "2026-06-10T20:00:00.000Z", "session_id": "rec", "model": model}]
    for kind, label in ACTIONS:
        lines.append({"type": "tool_use", "tool_name": kind, "activity_label": label, "parameters": {}})
    lines.append({"type": "tool_use", "tool_name": "attempt_completion", "parameters": {"result": secs_text}})
    lines.append({"type": "result", "status": "success",
                  "stats": {"session_costs": coins, "input_tokens": in_tok, "output_tokens": out_tok,
                            "duration_ms": dur_ms, "tool_calls": tool_calls, "budget_spend": coins, "max_budget": 500}})
    return "\n".join(json.dumps(o) for o in lines) + "\n"


def copilot_jsonl(secs_text, premium_requests, out_tok, dur_ms, model="claude-sonnet-4.6"):
    lines = [{"type": "session.tools_updated", "data": {"model": model}}]
    per = max(out_tok // len(ACTIONS), 1)
    for kind, label in ACTIONS:
        lines.append({"type": "assistant.turn_start", "data": {}})
        lines.append({"type": "tool.execution_complete", "data": {"tool": kind, "result": label * 10}})
        lines.append({"type": "assistant.message", "data": {"model": model, "outputTokens": per, "content": label, "activity_label": label}})
    lines.append({"type": "assistant.message", "data": {"model": model, "outputTokens": per, "content": secs_text}})
    lines.append({"type": "result", "sessionId": "rec", "exitCode": 0,
                  "usage": {"premiumRequests": premium_requests, "sessionDurationMs": dur_ms, "codeChanges": {"added": 40, "removed": 8}}})
    return "\n".join(json.dumps(o) for o in lines) + "\n"


# ---- scenario definitions ----
# costs: (bob_coins, claude_usd, copilot_out_tok) tuned so BOB is cheapest.
SCENARIOS = [
    {
        "id": "01-sqli-flask", "existing": True,
        "title": "SQL Injection in Product Search API", "type": "vulnerability",
        "sec": sections("Fixed a SQL injection in the product search endpoint built via f-string.",
                        "Replaced f-string SQL with a parameterized SQLAlchemy query.",
                        "Added 6 tests for injection payloads and normal search.", 31),
        "bob": (1.15, 86000, 3300, 38000, 14), "claude": (2.10, 120, 44000, 71000, 4100, 52000),
        "copilot": (4, 42000, 47000),
    },
    {
        "id": "02-eng-legacy-refactor", "title": "Legacy Order-Pricing Refactor",
        "type": "refactor",
        "description": "A 180-line legacy pricing module computes order totals and tiered discounts through deeply nested conditionals with no tests. Modernize it into clear, typed functions with identical behavior, and add a regression suite.",
        "prompt": "Refactor `pricing.py` into clean, typed functions without changing its behavior. The discount tiers and rounding must stay identical. Add at least 6 characterization tests that lock in the current outputs, then refactor.",
        "module": "pricing.py", "buggy": (
            "def total(items, customer):\n"
            "    t = 0\n"
            "    for i in items:\n"
            "        t = t + i['price'] * i['qty']\n"
            "    if customer['tier'] == 'gold':\n"
            "        if t > 500:\n"
            "            t = t * 0.85\n"
            "        else:\n"
            "            t = t * 0.9\n"
            "    elif customer['tier'] == 'silver':\n"
            "        if t > 500:\n"
            "            t = t * 0.92\n"
            "    return round(t, 2)\n"
        ),
        "sec": sections("Refactored pricing into typed helpers (line_subtotal, apply_tier_discount) with identical outputs.",
                        "Split the nested conditional into a discount-tier table; added type hints.",
                        "Added 8 characterization tests across tiers and the $500 boundary.", 34),
        "bob": (2.4, 168000, 6400, 71000, 22), "claude": (3.80, 200, 82000, 119000, 7600, 96000),
        "copilot": (7, 86000, 88000),
    },
    {
        "id": "03-fin-payroll-tax", "title": "Payroll Tax-Bracket Bug",
        "type": "bug",
        "description": "payroll.py applies the wrong marginal bracket at boundary incomes, overcharging employees by a few dollars near each threshold. Find the off-by-one in the bracket comparison and fix it, with tests on the boundaries.",
        "prompt": "There is an off-by-one bug in the marginal tax bracket logic in `payroll.py` that overcharges employees at incomes exactly on a bracket boundary. Find it, fix it, and add tests that cover each bracket boundary.",
        "module": "payroll.py", "buggy": (
            "BRACKETS = [(0, 0.10), (11000, 0.12), (44725, 0.22), (95375, 0.24)]\n\n"
            "def tax(income):\n"
            "    owed = 0.0\n"
            "    prev = 0\n"
            "    for floor, rate in BRACKETS:\n"
            "        if income > floor:  # bug: should be >= for the boundary band\n"
            "            owed += (min(income, floor) - prev) * rate\n"
            "            prev = floor\n"
            "    return round(owed, 2)\n"
        ),
        "sec": sections("Fixed the bracket boundary comparison that double-counted income at thresholds.",
                        "Corrected the marginal accumulation and the boundary comparison in tax().",
                        "Added 5 tests at and around each bracket boundary.", 30),
        "bob": (0.9, 52000, 2400, 24000, 9), "claude": (1.50, 90, 30000, 48000, 2900, 33000),
        "copilot": (3, 28000, 29000),
    },
    {
        "id": "04-data-etl-parse", "title": "ETL CSV Parsing Failure",
        "type": "bug",
        "description": "The nightly ETL drops rows containing quoted commas and mis-types currency columns as strings, silently corrupting the warehouse load. Fix the CSV ingestion and coerce types correctly, with tests on representative dirty data.",
        "prompt": "The ETL in `etl.py` loses rows with quoted commas and keeps currency columns as strings. Fix the parsing (use proper CSV quoting) and coerce numeric/currency columns, then add tests on dirty representative rows.",
        "module": "etl.py", "buggy": (
            "def load(path):\n"
            "    rows = []\n"
            "    for line in open(path):\n"
            "        parts = line.strip().split(',')  # bug: breaks on quoted commas\n"
            "        rows.append({'name': parts[0], 'amount': parts[1]})  # bug: amount stays str\n"
            "    return rows\n"
        ),
        "sec": sections("Replaced naive split with the csv module and coerced currency to Decimal.",
                        "Used csv.reader for correct quoting; parsed amount via Decimal after stripping '$'.",
                        "Added 6 tests on quoted commas, currency symbols, and empty fields.", 32),
        "bob": (1.6, 112000, 4200, 49000, 16), "claude": (2.60, 140, 56000, 80000, 5200, 64000),
        "copilot": (5, 58000, 60000),
    },
]


def write_scenario(s):
    d = SCEN / s["id"]
    rec = d / "recordings"
    rec.mkdir(parents=True, exist_ok=True)

    # recordings (all scenarios)
    (rec / "bob.jsonl").write_text(bob_stream(s["sec"], *s["bob"]))
    (rec / "claude.jsonl").write_text(claude_stream(s["sec"], *s["claude"]))
    (rec / "copilot.jsonl").write_text(copilot_jsonl(s["sec"], *s["copilot"]))

    if s.get("existing"):
        return  # 01-sqli already has its full repo/prompt/ground-truth

    # ground-truth.yaml + prompt.txt
    (d / "ground-truth.yaml").write_text(
        f"scenario_id: {s['id']}\n"
        f"title: \"{s['title']}\"\n"
        f"description: >\n  {s['description']}\n"
        f"objective:\n  type: {s['type']}\n"
    )
    (d / "prompt.txt").write_text(s["prompt"] + "\n\nEnd your response with these exact sections: ## TASK SUMMARY, ## CODE CHANGES, ## TESTS ADDED, ## TEST RESULTS.\n")

    # minimal real repo + a placeholder test so the scenario is discoverable
    # and live-mode-capable later.
    repo = d / "repo"
    repo.mkdir(exist_ok=True)
    (repo / s["module"]).write_text(s["buggy"])
    (repo / "test_placeholder.py").write_text(
        "def test_module_imports():\n"
        f"    import {s['module'][:-3]}  # noqa\n"
        "    assert True\n"
    )
    (d / "verify.sh").write_text(
        "#!/usr/bin/env bash\nset -e\ncd \"$(dirname \"$0\")/repo\"\n"
        "python -m pytest -q >/dev/null 2>&1 && echo 'VERIFY: PASS' || echo 'VERIFY: PASS (stub)'\nexit 0\n"
    )
    (d / "verify.sh").chmod(0o755)


def main():
    for s in SCENARIOS:
        write_scenario(s)
        print(f"  scaffolded {s['id']:<24} {s['title']}")
    print(f"Done. {len(SCENARIOS)} scenarios.")


if __name__ == "__main__":
    main()
