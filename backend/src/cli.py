"""Command-line entry point for the bake-off harness.

Usage:
    ./bakeoff run [SCENARIO_ID] [--tool bob|claude|copilot] [--timeout 600]
    ./bakeoff serve [--port 8765]
    ./bakeoff runs            # list run history
    ./bakeoff scenarios       # list available scenarios
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from rich.console import Console
from rich.table import Table

from src import orchestrator
from src.storage import db as storage_db


console = Console()


def cmd_scenarios(_args) -> int:
    scenarios = orchestrator.list_scenarios()
    if not scenarios:
        console.print("[yellow]No scenarios found in scenarios/[/]")
        return 0
    t = Table(title="Available scenarios", show_lines=True)
    t.add_column("ID", style="cyan")
    t.add_column("Title")
    t.add_column("Description")
    for s in scenarios:
        t.add_row(s["id"], s["title"], s["description"][:80])
    console.print(t)
    return 0


async def _do_run(scenario_id: str, tools: list[str], timeout: int) -> int:
    console.print(f"[bold]Running scenario:[/] {scenario_id}")
    console.print(f"[bold]Tools:[/] {', '.join(tools)}")
    console.print(f"[bold]Timeout:[/] {timeout}s per tool\n")

    # Per-tool queues so we can print line-by-line live
    queues = {t: asyncio.Queue() for t in tools}

    async def _stream(tool: str):
        while True:
            line = await queues[tool].get()
            if line is None:
                return
            console.print(f"[dim]\\[{tool}][/] {line.rstrip()}")

    streamers = [asyncio.create_task(_stream(t)) for t in tools]

    payload = await orchestrator.run_bakeoff(
        scenario_id=scenario_id,
        tools=tools,
        queues=queues,
        timeout_s=timeout,
    )
    await asyncio.gather(*streamers)

    _print_comparison(payload)
    return 0


def _print_comparison(payload: dict) -> None:
    console.print(f"\n[bold green]Run complete:[/] {payload['run_id']}")
    t = Table(title="Bake-off results", show_lines=True)
    t.add_column("Metric")
    for tool_row in payload["tools"]:
        t.add_column(tool_row["tool"], justify="right")

    t.add_row(
        "Wall clock",
        *[f"{r['wall_clock_ms']/1000:.1f}s" for r in payload["tools"]],
    )
    t.add_row(
        "USD cost",
        *[f"${r['usd_cost']:.4f}" for r in payload["tools"]],
    )
    t.add_row(
        "Native cost",
        *[f"{r['native_cost_value']:.4f} {r['native_cost_unit']}" for r in payload["tools"]],
    )
    t.add_row(
        "Input tokens",
        *[str(r.get("input_tokens") or "—") for r in payload["tools"]],
    )
    t.add_row(
        "Output tokens",
        *[str(r.get("output_tokens") or "—") for r in payload["tools"]],
    )
    t.add_row(
        "Model",
        *[str(r.get("model") or "—") for r in payload["tools"]],
    )

    # Verification rows — only meaningful if present
    def _vfield(r, key, default="—"):
        v = r.get("verification") or {}
        return str(v.get(key, default))

    t.add_row("Tests passed", *[_vfield(r, "tests_passed") for r in payload["tools"]])
    t.add_row("Tests failed", *[_vfield(r, "tests_failed") for r in payload["tools"]])
    t.add_row("New tests", *[_vfield(r, "new_tests_added") for r in payload["tools"]])
    t.add_row("Semgrep findings", *[_vfield(r, "semgrep_findings_total") for r in payload["tools"]])
    t.add_row(
        "Issue resolved",
        *["✓" if not (r.get("verification") or {}).get("vuln_pattern_still_present", True) else "✗"
          for r in payload["tools"]],
    )
    t.add_row("Lines changed", *[_vfield(r, "lines_changed") for r in payload["tools"]])

    console.print(t)

    # Per-tool summaries
    console.print("\n[bold]Per-tool self-reports:[/]")
    for r in payload["tools"]:
        s = r.get("summary") or {}
        console.print(f"\n[bold cyan]--- {r['tool']} ---[/]")
        for key, label in [
            ("vulnerabilities_found", "VULNERABILITIES FOUND"),
            ("fixes_applied", "FIXES APPLIED"),
            ("tests_added", "TESTS ADDED"),
            ("test_results", "TEST RESULTS"),
        ]:
            body = (s.get(key) or "").strip()
            if body:
                console.print(f"[bold]## {label}[/]\n{body}\n")
            else:
                console.print(f"[dim]## {label}: (not provided)[/]")


def cmd_run(args) -> int:
    scenario_id = args.scenario_id or os.environ.get("BAKEOFF_DEFAULT_SCENARIO", "01-sqli-flask")
    tools = [args.tool] if args.tool else None
    timeout = args.timeout or int(os.environ.get("BAKEOFF_TIMEOUT_SECONDS", "600"))
    return asyncio.run(_do_run(scenario_id, tools or ["bob", "claude", "copilot"], timeout))


def cmd_runs(_args) -> int:
    conn = storage_db.connect()
    try:
        rows = storage_db.list_runs(conn, limit=50)
    finally:
        conn.close()
    if not rows:
        console.print("[yellow]No past runs.[/]")
        return 0
    t = Table(title="Recent runs")
    t.add_column("Run ID")
    t.add_column("Scenario")
    t.add_column("Tool")
    t.add_column("Started")
    t.add_column("USD", justify="right")
    t.add_column("Status")
    for row in rows:
        status = "✓" if row.get("exit_code") == 0 else "✗"
        t.add_row(
            row["run_id"][:24],
            row["scenario_id"],
            row["tool"],
            (row["started_at"] or "")[:19],
            f"${(row['usd_cost'] or 0):.4f}",
            status,
        )
    console.print(t)
    return 0


def cmd_refresh_pricing(_args) -> int:
    from src.pricing.refresh import refresh
    changed, msg = refresh()
    console.print(("[green]✓[/] " if changed else "[yellow]·[/] ") + msg)
    return 0


def cmd_serve(args) -> int:
    import uvicorn
    port = args.port or int(os.environ.get("BAKEOFF_PORT", "8765"))
    # reload=True so edits to parsers/scoring/UI pick up without a manual
    # restart — without this, an in-memory copy of e.g. summary_extractor
    # keeps serving stale results until you Ctrl+C and re-serve.
    reload = os.environ.get("BAKEOFF_NO_RELOAD") != "1"
    console.print(f"[bold green]Starting server on http://localhost:{port}[/]"
                  + (" [dim](auto-reload on)[/]" if reload else ""))
    uvicorn.run(
        "src.server:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
        reload=reload,
        reload_dirs=["src", "frontend"] if reload else None,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bakeoff", description="Bake-off harness for Bob / Claude / Copilot"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="Run a scenario")
    pr.add_argument("scenario_id", nargs="?", help="Scenario ID (folder name)")
    pr.add_argument("--tool", choices=["bob", "claude", "copilot"],
                    help="Only run this tool (default: all three)")
    pr.add_argument("--timeout", type=int, help="Per-tool timeout in seconds")
    pr.set_defaults(func=cmd_run)

    sub.add_parser("scenarios", help="List available scenarios").set_defaults(func=cmd_scenarios)
    sub.add_parser("runs", help="List past runs").set_defaults(func=cmd_runs)
    sub.add_parser("refresh-pricing", help="Refresh model rates (stub for live pricing)").set_defaults(func=cmd_refresh_pricing)

    ps = sub.add_parser("serve", help="Launch the FastAPI web UI")
    ps.add_argument("--port", type=int, help="Port (default 8765)")
    ps.set_defaults(func=cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
