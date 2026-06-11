"""Async subprocess runner base class.

Each concrete runner spawns its CLI tool, streams stdout line-by-line
into an asyncio.Queue (for live UI), captures full stdout/stderr to
files in the run directory, and returns a partially-populated
RunResult that the orchestrator finishes filling in (summary,
verification, pricing).
"""
from __future__ import annotations

import abc
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.models.run_result import RunResult


class Runner(abc.ABC):
    """Each tool subclasses this and implements `command()`."""

    tool_name: str

    @abc.abstractmethod
    def command(self, prompt: str, env_overrides: Optional[dict] = None) -> list[str]:
        """Return the argv to spawn this tool with the given prompt."""

    def env(self) -> dict[str, str]:
        """Return env vars for the subprocess (inherits os.environ by default)."""
        return dict(os.environ)

    async def run(
        self,
        scenario_id: str,
        working_dir: Path,
        prompt: str,
        run_dir: Path,
        output_queue: Optional[asyncio.Queue] = None,
        timeout_s: int = 600,
    ) -> RunResult:
        """Spawn the tool, stream stdout, return a partial RunResult."""
        run_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        argv = self.command(prompt)

        result = RunResult(
            tool=self.tool_name,
            scenario_id=scenario_id,
            started_at=datetime.now(timezone.utc),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            working_copy_path=str(working_dir),
        )

        # Save the exact command for reproducibility
        (run_dir / "command.txt").write_text(" ".join(repr(a) if " " in a else a for a in argv))

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=working_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env(),
            )
        except FileNotFoundError as e:
            result.error = f"CLI not found: {e}"
            result.exit_code = 127
            result.completed_at = datetime.now(timezone.utc)
            return result

        # Open stdout/stderr files in line-buffered append mode so we have
        # a partial trace even if the process is killed or hangs.
        stdout_f = open(stdout_path, "wb", buffering=0)
        stderr_f = open(stderr_path, "wb", buffering=0)

        async def _consume(stream, fout, queue):
            while True:
                line = await stream.readline()
                if not line:
                    break
                try:
                    fout.write(line)
                except Exception:
                    pass
                if queue is not None:
                    try:
                        await queue.put(line.decode("utf-8", errors="replace"))
                    except Exception:
                        pass

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _consume(proc.stdout, stdout_f, output_queue),
                    _consume(proc.stderr, stderr_f, None),
                    proc.wait(),
                ),
                timeout=timeout_s,
            )
            result.exit_code = proc.returncode if proc.returncode is not None else -1
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            result.error = f"timed out after {timeout_s}s"
            result.exit_code = -1
        finally:
            stdout_f.close()
            stderr_f.close()

        result.completed_at = datetime.now(timezone.utc)
        result.wall_clock_ms = int(
            (result.completed_at - result.started_at).total_seconds() * 1000
        )

        # The orchestrator is responsible for emitting the final "tool
        # finished" marker into the queue after it runs post-processing,
        # so the SSE stream can deliver the parsed cost/tokens/summary
        # in the same `done` event. We do NOT push a None sentinel here.
        return result
