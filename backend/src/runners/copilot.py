"""Runner for GitHub Copilot CLI.

Invocation:
    copilot -p "<prompt>" --yolo --output-format json [--model <m>]

--output-format json is JSONL (streaming events, one per line).
"""
from __future__ import annotations

import os

from src.runners.base import Runner
from src.runners.resolve import resolve_bin


class CopilotRunner(Runner):
    tool_name = "copilot"

    def command(self, prompt: str, env_overrides=None) -> list[str]:
        # `--no-remote` disables the GitHub web/mobile remote-control
        # socket. `--disable-builtin-mcps` skips the built-in
        # github-mcp-server (we don't need GitHub integration for code-
        # review scenarios). Both have caused hang/stall reports in the
        # field; off by default keeps the bake-off snappy.
        argv = [
            resolve_bin("copilot") or "copilot",
            "-p", prompt,
            "--yolo",
            "--no-remote",
            "--disable-builtin-mcps",
            "--output-format", "json",
        ]
        model = os.environ.get("COPILOT_MODEL")
        if model:
            argv.extend(["--model", model])
        return argv
