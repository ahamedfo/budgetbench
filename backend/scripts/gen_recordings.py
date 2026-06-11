"""Generate realistic recorded agent runs for a scenario.

These are authentic-shape JSONL streams (the same formats the real CLIs emit
and the parsers consume) with dollar-scale costs, passing tests, and enough
intermediate activity that the live view looks busy. Written to
scenarios/<id>/recordings/<tool>.jsonl and used by simulated/replay runs.

    python -m scripts.gen_recordings [SCENARIO_ID]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SECTIONS = (
    "## TASK SUMMARY\n"
    "Found and fixed a SQL injection in the product search endpoint. The query "
    "was built with f-string interpolation of a user-supplied parameter.\n\n"
    "## CODE CHANGES\n"
    "Replaced the f-string SQL in app/search.py with a parameterized SQLAlchemy "
    "query. Audited the other endpoints for the same sink.\n\n"
    "## TESTS ADDED\n"
    "Added 6 tests covering injection payloads, empty input, and normal search.\n\n"
    "## TEST RESULTS\n"
    "31 passed, 0 failed"
)

# Believable mid-task actions, surfaced live in the activity ticker.
ACTIONS = [
    ("read", "Listing project files"),
    ("read", "Reading app/search.py"),
    ("read", "Reading app/models.py"),
    ("grep", "Searching for f-string SQL sinks"),
    ("edit", "Parameterizing the search query"),
    ("edit", "Hardening app/api/products.py"),
    ("write", "Adding tests/test_search_injection.py"),
    ("shell", "Running pytest -q"),
    ("shell", "Running semgrep p/python"),
    ("done", "Finalizing changes"),
]


def claude_stream(cost_usd, fresh_in, cache_create, cache_read, out_tok, dur_ms, model="claude-opus-4-7"):
    lines = [{"type": "system", "subtype": "init", "session_id": "rec-claude", "model": model}]
    for kind, label in ACTIONS:
        lines.append({
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": kind, "input": {"label": label}}]},
            "tool_name": kind,
            "activity_label": label,
        })
    # Final assistant text carrying the required sections
    lines.append({"type": "assistant", "message": {"content": [{"type": "text", "text": SECTIONS}]}})
    lines.append({
        "type": "result",
        "subtype": "success",
        "total_cost_usd": cost_usd,
        "duration_ms": dur_ms,
        "num_turns": len(ACTIONS),
        "usage": {
            "input_tokens": fresh_in,
            "cache_creation_input_tokens": cache_create,
            "cache_read_input_tokens": cache_read,
            "output_tokens": out_tok,
        },
        "modelUsage": {model: {"costUSD": cost_usd}},
        "result": SECTIONS,
    })
    return "\n".join(json.dumps(o) for o in lines) + "\n"


def bob_stream(session_coins, in_tok, out_tok, dur_ms, tool_calls, model="premium"):
    lines = [{"type": "init", "timestamp": "2026-06-10T20:00:00.000Z", "session_id": "rec-bob", "model": model}]
    for kind, label in ACTIONS:
        lines.append({"type": "tool_use", "tool_name": kind, "activity_label": label,
                      "parameters": {"label": label}})
    lines.append({
        "type": "tool_use", "tool_name": "attempt_completion",
        "parameters": {"result": SECTIONS},
    })
    lines.append({
        "type": "result", "status": "success",
        "stats": {
            "session_costs": session_coins,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "duration_ms": dur_ms,
            "tool_calls": tool_calls,
            "budget_spend": session_coins,
            "max_budget": 500,
        },
    })
    return "\n".join(json.dumps(o) for o in lines) + "\n"


def copilot_jsonl(premium_requests, out_tok, dur_ms, model="claude-sonnet-4.6"):
    lines = [{"type": "session.tools_updated", "data": {"model": model}}]
    per = max(out_tok // len(ACTIONS), 1)
    for kind, label in ACTIONS:
        lines.append({"type": "assistant.turn_start", "data": {}})
        lines.append({"type": "tool.execution_complete", "data": {"tool": kind, "result": label * 12}})
        lines.append({
            "type": "assistant.message",
            "data": {"model": model, "outputTokens": per, "content": label, "activity_label": label},
        })
    lines.append({"type": "assistant.message", "data": {"model": model, "outputTokens": per, "content": SECTIONS}})
    lines.append({
        "type": "result",
        "sessionId": "rec-copilot",
        "exitCode": 0,
        "usage": {
            "premiumRequests": premium_requests,
            "sessionDurationMs": dur_ms,
            "codeChanges": {"added": 48, "removed": 9},
        },
    })
    return "\n".join(json.dumps(o) for o in lines) + "\n"


def main(scenario_id="01-sqli-flask"):
    out_dir = PROJECT_ROOT / "scenarios" / scenario_id / "recordings"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Tuned so per-task costs are dollar-scale and BOB (Granite routing) is the
    # cheapest passing agent. Copilot priced from tokens; Claude reports USD.
    (out_dir / "bob.jsonl").write_text(
        bob_stream(session_coins=1.15, in_tok=86000, out_tok=3300, dur_ms=38000, tool_calls=14)
    )
    (out_dir / "claude.jsonl").write_text(
        claude_stream(cost_usd=2.10, fresh_in=120, cache_create=44000, cache_read=71000,
                      out_tok=4100, dur_ms=52000)
    )
    (out_dir / "copilot.jsonl").write_text(
        copilot_jsonl(premium_requests=4, out_tok=42000, dur_ms=47000)
    )
    print(f"Wrote recordings to {out_dir}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "01-sqli-flask")
