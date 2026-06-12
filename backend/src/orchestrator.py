"""Parallel runner manager.

Stages working copies, spawns all 3 runners concurrently, streams their
output, then runs post-processing (parser → summary → verifier →
pricing) and persists to SQLite + comparison.json.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from src.display_labels import display_model_for_row
from src.models.run_result import RunResult
from src.parsers import ParseError
from src.parsers.bob_parser import parse_bob_stdout
from src.parsers.claude_parser import parse_claude_stdout
from src.parsers.copilot_parser import parse_copilot_stdout
from src.pricing.calculator import PricingError, compute_cost
from src.runners.base import Runner
from src.runners.bob import BobRunner
from src.runners.claude import ClaudeRunner
from src.runners.copilot import CopilotRunner
from src.runners.simulated import FixtureRunner, fixture_for
from src.runners.resolve import agent_available
from src.scoring.objective_verifier import verify
from src.scoring.summary_extractor import extract_sections
from src.storage import db as storage_db


# run_mode values. "live" spawns the real CLIs; the other two re-stream a
# saved JSONL fixture through the same pipeline (see runners/simulated.py).
LIVE = "live"
REPLAY = "replay"
SIMULATED = "simulated"
REPLAY_MODES = {REPLAY, SIMULATED}


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = PROJECT_ROOT / "scenarios"
RUNS_DIR = PROJECT_ROOT / "runs"


RUNNERS: dict[str, type[Runner]] = {
    "bob": BobRunner,
    "claude": ClaudeRunner,
    "copilot": CopilotRunner,
}

PARSERS = {
    "bob": parse_bob_stdout,
    "claude": parse_claude_stdout,
    "copilot": parse_copilot_stdout,
}


def list_scenarios() -> list[dict]:
    """Discover scenarios on disk and return their UI-visible metadata.
    Any folder under scenarios/ with ground-truth.yaml + prompt.txt +
    repo/ is picked up automatically — no code change needed to add one."""
    out = []
    if not SCENARIOS_DIR.exists():
        return out
    for d in sorted(SCENARIOS_DIR.iterdir()):
        if not d.is_dir():
            continue
        gt_path = d / "ground-truth.yaml"
        prompt_path = d / "prompt.txt"
        repo_path = d / "repo"
        verify_sh = d / "verify.sh"
        # All four are required for a scenario to be discovered. A folder
        # missing any of them is silently skipped — keeps malformed
        # in-progress scenarios from breaking the UI.
        if not (gt_path.exists() and prompt_path.exists()
                and repo_path.exists() and verify_sh.exists()):
            continue
        try:
            gt = yaml.safe_load(gt_path.read_text())
        except Exception:
            gt = {}
        # Build the "verifications applied" summary that gets shown
        # under each scenario in the UI, so the audience knows exactly
        # which checks ran for this scenario.
        semgrep_cfg = (gt.get("semgrep_config")
                       or (gt.get("objective") or {}).get("semgrep_config")
                       or (gt.get("vulnerability") or {}).get("semgrep_config"))
        verifications = ["pytest", "verify.sh"]
        if semgrep_cfg:
            verifications.append(f"semgrep ({semgrep_cfg})")
        forbidden = gt.get("forbidden_patterns") or []
        if forbidden:
            verifications.append(f"{len(forbidden)} forbidden pattern{'' if len(forbidden) == 1 else 's'}")

        out.append({
            "id": d.name,
            "title": gt.get("title", d.name),
            "description": (gt.get("description") or "").strip(),
            "prompt": prompt_path.read_text().strip(),
            "objective_type": ((gt.get("objective") or {}).get("type")
                               or (gt.get("vulnerability") or {}).get("type")
                               or "task"),
            "verifications": verifications,
            "vulnerability": gt.get("vulnerability", {}),
        })
    return out


def stage_working_copy(scenario_dir: Path, tool: str, run_dir: Path) -> Path:
    """Fresh-copy the scenario repo into the tool's working dir.
    Also save a `.original/` snapshot for diffing.
    For Bob, drop a `.bob/rules/` workspace-rules file so Bob trims its
    mid-task chatter (saves tokens / bobcoins) without touching the
    required final ## section structure."""
    working = run_dir / tool / "working-copy"
    original = run_dir / tool / ".original"
    if working.exists():
        shutil.rmtree(working)
    if original.exists():
        shutil.rmtree(original)
    # ignore_dangling_symlinks for safety; copy permissions
    shutil.copytree(scenario_dir / "repo", working, symlinks=False)
    shutil.copytree(scenario_dir / "repo", original, symlinks=False)

    if tool == "bob":
        _install_bob_workspace_rules(working)
    return working


# Workspace rule we drop into every Bob run's working-copy. Bob reads
# `.bob/rules/*.md` automatically (per IBM Bob "Custom rules" docs) and
# layers them on top of mode customInstructions. We keep the rule tight
# so it doesn't override the prompt's required final-response format.
_BOB_RULE_TOKEN_THRIFT = """\
# Output efficiency

Trim the mid-task chatter. Specifically:

- Skip preamble like "Let me first check…", "I'll start by…", "Now I will…".
  Just do the thing.
- Don't restate the plan after every tool call. One short status line is fine.
- Don't quote large code blocks back verbatim when describing a change —
  point at the file + line and summarize what shifted.
- Don't repeat earlier reasoning in `<thinking>` blocks; assume the user
  has the previous turn in front of them.

These limits apply ONLY to intermediate steps. The FINAL
`attempt_completion` response MUST still include all four section headers
exactly as the prompt requested:

  ## TASK SUMMARY
  ## CODE CHANGES
  ## TESTS ADDED
  ## TEST RESULTS

…each with its full content. Brevity ≠ truncating the deliverable.

# Thoroughness — non-negotiable

Token savings must NEVER come at the cost of correctness or completeness.
Quieter output is fine; cutting corners on the actual work is not. In
particular:

- If the task is a bug fix, hunt the bug to its root cause; don't patch
  the symptom and move on. Verify the fix with a test that would have
  caught the original bug.
- If the task is a security issue, address the actual vulnerability
  class, not just the one line that triggered detection. Check for
  related sinks (other endpoints, other query builders, similar
  patterns elsewhere in the codebase) and fix them too if present.
- If the task is a feature, implement the full feature including the
  edge cases a real user would hit (empty input, missing fields,
  auth/permission boundaries, error paths) — not just the happy path.
- If the task is a refactor or performance change, the behavior must
  stay identical. Verify by re-running the whole test suite.
- Always run the existing test suite end-to-end before reporting done.
  A green pytest is the floor, not the ceiling.
- When uncertain whether a related issue exists, look. A 30-second
  grep is cheaper than shipping an incomplete fix.

Be quick with words. Be careful with code.
"""


def _install_bob_workspace_rules(working: Path) -> None:
    """Write our workspace rule into the Bob cwd. Idempotent."""
    rules_dir = working / ".bob" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "01-token-thrift.md").write_text(_BOB_RULE_TOKEN_THRIFT)


def _runner_for(tool: str, run_mode: str, run_dir: Path, scenario_id: str | None = None) -> Runner:
    """Pick the runner for a tool given the run mode.

    live      → the real CLI runner (BobRunner / ClaudeRunner / CopilotRunner)
    replay    → re-stream this run_dir's previously captured stdout.log, if
                present; otherwise fall back to the scenario/bundled fixture
    simulated → re-stream the scenario recording (or bundled per-tool fixture)
    """
    if run_mode == LIVE:
        return RUNNERS[tool]()
    # replay/simulated → FixtureRunner. Prefer a prior captured stdout.log
    # for this tool when replaying; else the scenario recording / bundled fixture.
    fixture = None
    if run_mode == REPLAY:
        prior = run_dir / tool / "stdout.log"
        if prior.exists():
            fixture = prior
    return FixtureRunner(tool, fixture_path=fixture, scenario_id=scenario_id)


async def run_single_tool(
    tool: str,
    scenario_id: str,
    working_dir: Path,
    prompt: str,
    run_dir: Path,
    output_queue: Optional[asyncio.Queue] = None,
    timeout_s: int = 600,
    run_mode: str = LIVE,
) -> RunResult:
    runner = _runner_for(tool, run_mode, run_dir, scenario_id=scenario_id)
    return await runner.run(
        scenario_id=scenario_id,
        working_dir=working_dir,
        prompt=prompt,
        run_dir=run_dir / tool,
        output_queue=output_queue,
        timeout_s=timeout_s,
    )


import re as _re

from src.models.run_result import VerificationResult


def _synth_verification(result: RunResult) -> VerificationResult:
    """Build a verification result for replay/simulated runs.

    In replay/simulated mode the working-copy is never actually modified,
    so running pytest/semgrep against it would be meaningless. Instead we
    surface what the recorded run *reported* in its own ## TEST RESULTS
    section (e.g. "29 passed"). Honest: it reflects the captured run, and
    the UI tags the run as replayed.
    """
    v = VerificationResult()
    tr = (result.summary.test_results if result.summary else "") or ""
    m = _re.search(r"(\d+)\s+passed", tr)
    if m:
        v.tests_passed = int(m.group(1))
        v.tests_total = v.tests_passed
    mf = _re.search(r"(\d+)\s+failed", tr)
    if mf:
        v.tests_failed = int(mf.group(1))
        v.tests_total += v.tests_failed
    v.verify_sh_passed = v.tests_total > 0 and v.tests_failed == 0
    v.verify_sh_exit_code = 0 if v.verify_sh_passed else 1
    return v


def post_process(
    result: RunResult,
    scenario_dir: Path,
    run_dir: Path,
    run_mode: str = LIVE,
) -> RunResult:
    """Parse stdout, extract summary, run objective verification, compute USD cost."""
    if result.error:
        # We still try to parse + verify what we can
        pass

    raw = ""
    if result.stdout_path and Path(result.stdout_path).exists():
        raw = Path(result.stdout_path).read_text(errors="replace")

    # Capture runtime config that the UI needs for clean labels:
    #   - Bob: the chat-mode (advanced/code/plan/ask) the runner used
    #   - Copilot: any active display-as projection target
    if result.tool == "bob":
        result.extras.setdefault("chat_mode", os.environ.get("BOB_CHAT_MODE", "advanced"))
    if result.tool == "copilot":
        proj = os.environ.get("COPILOT_DISPLAY_AS_MODEL")
        if proj:
            result.extras.setdefault("display_as_model", proj.strip())

    parser = PARSERS[result.tool]
    try:
        parsed = parser(raw)
        result.native_cost_value = parsed.native_cost_value
        result.native_cost_unit = parsed.native_cost_unit
        result.input_tokens = parsed.input_tokens
        result.output_tokens = parsed.output_tokens
        result.cached_tokens = parsed.cached_tokens
        result.model = parsed.model
        result.extras = parsed.extras
        # Agent-reported task duration (recorded runs carry this; falls back
        # to the runner's wall-clock when absent).
        result.extras["duration_ms"] = parsed.duration_ms or result.wall_clock_ms
        # Build summary from parsed.response_text
        result.summary = extract_sections(parsed.response_text)
        # If the tool's stream contained a session-level error (currently
        # only Copilot surfaces these; e.g. rate_limit on Free plan),
        # promote it to the top-level error field so the UI can render
        # a warning badge on the column header without parsing extras.
        sess_err = (parsed.extras or {}).get("session_error")
        if sess_err and sess_err.get("type"):
            result.error = f"{sess_err['type']}: {sess_err.get('message','')}".strip()
    except ParseError as e:
        result.error = (result.error or "") + f" parse_error: {e}"
        result.summary = extract_sections(raw)

    # Pricing — pass model + tokens so Copilot token-based pricing works
    try:
        actual_model = result.model
        pricing = compute_cost(
            result.tool,
            result.native_cost_value,
            model=actual_model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cached_tokens=result.cached_tokens,
        )
        result.usd_cost = pricing.usd_cost
        pricing_payload = {
            "native_value": pricing.native_value,
            "native_unit": pricing.native_unit,
            "usd_cost": pricing.usd_cost,
            "rate_source": pricing.rate_source,
            "effective_value": pricing.effective_value,
            "actual_model": actual_model,
            "priced_as_model": pricing.model,
            "is_projection": (pricing.model != actual_model)
                             if (pricing.model and actual_model) else False,
            # Math-breakdown payload — UI uses these to render the
            # `tokens × rate = USD` (Copilot) and `coins × rate = USD`
            # (Bob) calculations on the report.
            "rate_breakdown": pricing.rate_breakdown,
            "usd_per_unit": pricing.usd_per_unit,
        }
        result.extras["pricing"] = pricing_payload
        # Compute the customer-facing model label ONCE here and persist it,
        # so historical runs render exactly the same in the report page
        # and the live UI, regardless of any later env-var changes.
        result.extras["display_model"] = display_model_for_row(
            result.tool, result.model, result.extras
        )
    except PricingError as e:
        result.error = (result.error or "") + f" pricing_error: {e}"

    # Tag the run mode so the UI can badge replayed/simulated runs honestly.
    result.extras["run_mode"] = run_mode

    # In replay/simulated mode the working-copy was never modified, so real
    # objective verification is meaningless — synthesize from the recorded
    # run's self-reported test results instead.
    if run_mode in REPLAY_MODES:
        result.verification = _synth_verification(result)
        return result

    # Objective verification — read scenario config.
    # Schema (all OPTIONAL; check is skipped when its key is absent):
    #   semgrep_config: <ruleset>     # e.g. p/python
    #   forbidden_patterns: [<regex>] # patterns that MUST NOT appear
    # We also accept the legacy nested form (vulnerability.semgrep_config)
    # so older scenarios keep working without rewriting.
    gt = yaml.safe_load((scenario_dir / "ground-truth.yaml").read_text())
    forbidden = gt.get("forbidden_patterns") or []
    semgrep_config = (
        gt.get("semgrep_config")
        or (gt.get("objective") or {}).get("semgrep_config")
        or (gt.get("vulnerability") or {}).get("semgrep_config")
        or None
    )
    working = run_dir / result.tool / "working-copy"
    original = run_dir / result.tool / ".original"
    verify_sh = scenario_dir / "verify.sh"
    if working.exists():
        try:
            result.verification = verify(
                working_copy=working,
                original_snapshot=original if original.exists() else None,
                forbidden_patterns=forbidden,
                semgrep_config=semgrep_config,
                verify_sh=verify_sh if verify_sh.exists() else None,
            )
        except Exception as e:
            result.error = (result.error or "") + f" verify_error: {e}"

    return result


async def run_bakeoff(
    scenario_id: str,
    tools: Optional[list[str]] = None,
    queues: Optional[dict[str, asyncio.Queue]] = None,
    timeout_s: int = 600,
    progress_callback=None,
    run_mode: str = LIVE,
    department_id: Optional[int] = None,
    submitter: Optional[str] = None,
) -> dict:
    """Top-level entry: stage, run, verify, persist."""
    scenario_dir = SCENARIOS_DIR / scenario_id
    if not scenario_dir.exists():
        raise FileNotFoundError(f"Scenario not found: {scenario_id}")
    prompt = (scenario_dir / "prompt.txt").read_text()
    tools = tools or list(RUNNERS.keys())

    run_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}-{scenario_id}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Stage all working copies (synchronous — fast)
    for t in tools:
        stage_working_copy(scenario_dir, t, run_dir)

    # Launch in parallel. As each tool finishes, immediately do its
    # post-processing (parsing → summary → verification → pricing) and
    # push the processed row into that tool's queue as a `_done` marker
    # so the SSE stream can emit the cost/tokens/summary the moment
    # that tool wraps up — no waiting for the others.
    async def _go(t: str) -> RunResult:
        q = queues.get(t) if queues else None
        # Hybrid live: in live mode, an agent runs for real only if its CLI
        # is available; otherwise it falls back to its recording (replay) so
        # the demo still completes. Each agent gets its own effective mode.
        eff_mode = run_mode
        if run_mode == LIVE and not agent_available(t):
            eff_mode = REPLAY
        runner_result = await run_single_tool(
            tool=t,
            scenario_id=scenario_id,
            working_dir=run_dir / t / "working-copy",
            prompt=prompt,
            run_dir=run_dir,
            output_queue=q,
            timeout_s=timeout_s,
            run_mode=eff_mode,
        )
        # Per-tool post-processing happens here, in parallel with other
        # tools still running, so the UI updates as each finishes.
        processed = post_process(runner_result, scenario_dir, run_dir, run_mode=eff_mode)
        if q is not None:
            await q.put({"_done": True, "row": processed.to_dict()})
        return processed

    processed: list[RunResult] = await asyncio.gather(*[_go(t) for t in tools])

    # Persist to comparison.json + SQLite
    payload = {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "run_mode": run_mode,
        "department_id": department_id,
        "submitter": submitter,
        "started_at": min(r.started_at for r in processed).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "tools": [r.to_dict() for r in processed],
    }
    (run_dir / "comparison.json").write_text(json.dumps(payload, indent=2, default=str))

    conn = storage_db.connect()
    try:
        for r in processed:
            # Persist each agent's EFFECTIVE mode (a live request can fall
            # back to replay per-agent when its CLI isn't installed).
            storage_db.save_run(
                conn, run_id, r,
                run_mode=(r.extras or {}).get("run_mode", run_mode),
                department_id=department_id,
                submitter=submitter,
            )
    finally:
        conn.close()

    return payload
