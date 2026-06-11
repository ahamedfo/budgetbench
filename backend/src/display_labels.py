"""Shared label-formatting for per-tool UI display.

Used by:
  - the orchestrator at save time (so the value is persisted in extras)
  - the server's Jinja templates (as a fallback for old runs without
    `display_model` saved)
  - the live-view JS, which mirrors this in app.js
"""
from __future__ import annotations

import re


def prettify_model(name: str | None) -> str:
    """'claude-opus-4-7' → 'Opus 4.7', 'claude-sonnet-4.6' → 'Sonnet 4.6'."""
    if not name:
        return "—"
    s = name
    for pref in ("claude-", "anthropic."):
        if s.lower().startswith(pref):
            s = s[len(pref):]
            break
    s = re.sub(r"-(\d+)-(\d+)$", r"-\1.\2", s)
    m = re.match(r"^([a-z0-9]+)-(.+)$", s, flags=re.IGNORECASE)
    if not m:
        return s
    family = m.group(1)
    family = family if family.isupper() else family.capitalize()
    return f"{family} {m.group(2)}"


def display_model_for_row(tool: str, model: str | None, extras: dict | None) -> str:
    """Customer-facing model label. Bob is ALWAYS recomputed from
    chat_mode (cheap, deterministic — older runs persisted a stale
    "Advanced mode" string we don't want to keep showing). Claude and
    Copilot prefer the persisted display_model so projection labels
    are stable across env-var changes."""
    extras = extras or {}

    if tool == "bob":
        mode = extras.get("chat_mode") or "advanced"
        return mode.capitalize()

    if extras.get("display_model"):
        return extras["display_model"]

    if tool == "copilot":
        pricing = extras.get("pricing") or {}
        target = pricing.get("priced_as_model") or model
        return prettify_model(target)

    return prettify_model(model)
