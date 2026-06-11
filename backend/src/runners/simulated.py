"""Fixture-replay runner — runs without any CLI installed.

Used for run_mode in {"simulated", "replay"}. It re-streams a saved JSONL
fixture (a previously captured tool output) line-by-line into the output
queue at a realistic pace, writing the exact same `stdout.log` a real run
would produce. The orchestrator's normal pipeline (parser → summary →
pricing) then runs over that stdout.log, so the cost/token numbers are the
*real* numbers recorded in the fixture — not invented.

Two modes share this runner:
  - "replay"     → re-stream a specific prior run's stdout.log (authentic).
  - "simulated"  → re-stream the bundled per-tool fixture under
                   backend/fixtures/replay/<tool>.jsonl (for dev / offline
                   demos when no real run has been recorded yet).

Why this matters for a SALES tool: a live agent can rate-limit, flake, or
go off-script mid-demo. Replay guarantees a flawless, deterministic run
that still shows genuine recorded economics.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.models.run_result import RunResult
from src.runners.base import Runner


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPLAY_FIXTURES_DIR = PROJECT_ROOT / "fixtures" / "replay"
SCENARIOS_DIR = PROJECT_ROOT / "scenarios"

# Seconds between streamed lines. Kept small so a demo doesn't drag, but
# non-zero so the audience actually sees the stream build up live.
DEFAULT_PACE_S = float(os.environ.get("SIM_PACE_SECONDS", "0.18"))


def fixture_for(tool: str, scenario_id: str | None = None) -> Path:
    """Pick the recorded fixture for a tool. Prefers a scenario-specific
    recording (scenarios/<id>/recordings/<tool>.jsonl) so each scenario can
    show realistic, on-topic economics; falls back to the bundled fixture."""
    if scenario_id:
        scoped = SCENARIOS_DIR / scenario_id / "recordings" / f"{tool}.jsonl"
        if scoped.exists():
            return scoped
    return REPLAY_FIXTURES_DIR / f"{tool}.jsonl"


class FixtureRunner(Runner):
    """Replays a saved JSONL fixture for `tool_name`, no subprocess."""

    def __init__(
        self,
        tool_name: str,
        fixture_path: Optional[Path] = None,
        pace_s: float = DEFAULT_PACE_S,
        scenario_id: Optional[str] = None,
    ):
        self.tool_name = tool_name
        self.fixture_path = Path(fixture_path) if fixture_path else fixture_for(tool_name, scenario_id)
        self.pace_s = pace_s

    def command(self, prompt: str, env_overrides=None) -> list[str]:
        # Never spawned — present for the abstract base contract only.
        return ["#replay", self.tool_name, str(self.fixture_path)]

    async def run(
        self,
        scenario_id: str,
        working_dir: Path,
        prompt: str,
        run_dir: Path,
        output_queue: Optional[asyncio.Queue] = None,
        timeout_s: int = 600,
    ) -> RunResult:
        run_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"

        result = RunResult(
            tool=self.tool_name,
            scenario_id=scenario_id,
            started_at=datetime.now(timezone.utc),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            working_copy_path=str(working_dir),
        )
        (run_dir / "command.txt").write_text(
            f"[replay] {self.tool_name} <- {self.fixture_path}"
        )

        if not self.fixture_path.exists():
            result.error = f"replay fixture not found: {self.fixture_path}"
            result.exit_code = 127
            result.completed_at = datetime.now(timezone.utc)
            stderr_path.write_text(result.error)
            return result

        lines = self.fixture_path.read_text(errors="replace").splitlines(keepends=True)
        with open(stdout_path, "wb", buffering=0) as fout:
            for line in lines:
                fout.write(line.encode("utf-8", errors="replace"))
                if output_queue is not None:
                    out_line = line if line.endswith("\n") else line + "\n"
                    try:
                        await output_queue.put(out_line)
                    except Exception:
                        pass
                await asyncio.sleep(self.pace_s)
        stderr_path.write_text("")

        result.exit_code = 0
        result.completed_at = datetime.now(timezone.utc)
        result.wall_clock_ms = int(
            (result.completed_at - result.started_at).total_seconds() * 1000
        )
        result.extras["replayed_from"] = str(self.fixture_path)
        return result
