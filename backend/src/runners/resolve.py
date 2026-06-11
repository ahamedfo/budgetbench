"""Resolve each agent's CLI binary + report availability.

Live mode needs to know which agents can actually run. An agent is
"available" if we can find an executable for it, via (in order):
  1. an explicit env override  (CLAUDE_BIN / BOB_BIN / COPILOT_BIN)
  2. the name on PATH           (shutil.which)
  3. ~/.local/bin/<tool>        (common user install location)
"""
from __future__ import annotations

import os
import shutil

_BIN_ENV = {"claude": "CLAUDE_BIN", "bob": "BOB_BIN", "copilot": "COPILOT_BIN"}


def resolve_bin(tool: str) -> str | None:
    candidates: list[str] = []
    override = os.environ.get(_BIN_ENV.get(tool, ""))
    if override:
        candidates.append(os.path.expanduser(override))
    on_path = shutil.which(tool)
    if on_path:
        candidates.append(on_path)
    candidates.append(os.path.expanduser(f"~/.local/bin/{tool}"))

    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def agent_available(tool: str) -> bool:
    return resolve_bin(tool) is not None


def availability() -> list[dict]:
    """Per-agent live readiness for the UI."""
    out = []
    for tool in ("bob", "claude", "copilot"):
        b = resolve_bin(tool)
        out.append({"tool": tool, "live_ready": b is not None, "bin": b})
    return out
