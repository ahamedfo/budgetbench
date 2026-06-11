"""Runner for IBM Bob Shell.

Invocation:
    bob "<prompt>" -y --chat-mode advanced --output-format stream-json [--model <m>]

`--chat-mode advanced` gives Bob full agentic capabilities (vs. the
plainer default modes like 'code' or 'ask'). Overridable via
BOB_CHAT_MODE env var.
"""
from __future__ import annotations

import os

from src.runners.base import Runner
from src.runners.resolve import resolve_bin


class BobRunner(Runner):
    tool_name = "bob"

    def command(self, prompt: str, env_overrides=None) -> list[str]:
        chat_mode = os.environ.get("BOB_CHAT_MODE", "advanced")
        argv = [
            resolve_bin("bob") or "bob", prompt,
            "-y",
            "--chat-mode", chat_mode,
            "--output-format", "stream-json",
        ]
        model = os.environ.get("BOB_MODEL")
        if model:
            argv.extend(["--model", model])
        return argv
