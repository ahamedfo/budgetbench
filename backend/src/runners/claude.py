"""Runner for Anthropic Claude Code.

Invocation:
    claude -p "<prompt>" --output-format stream-json --verbose
        --dangerously-skip-permissions [--model <m>]

--verbose is required when combining --print + --output-format stream-json.
"""
from __future__ import annotations

import os

from src.runners.base import Runner
from src.runners.resolve import resolve_bin


class ClaudeRunner(Runner):
    tool_name = "claude"

    def command(self, prompt: str, env_overrides=None) -> list[str]:
        argv = [
            resolve_bin("claude") or "claude",
            "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
        ]
        model = os.environ.get("CLAUDE_MODEL")
        if model:
            argv.extend(["--model", model])
        return argv
