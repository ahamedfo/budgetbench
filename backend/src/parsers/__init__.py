"""Per-tool stdout parsers.

Each parser takes the captured stdout (typically JSONL stream-json or
a single-blob JSON envelope) and returns a `ParsedToolOutput`:

- native_cost_value, native_cost_unit  (raw cost in the tool's unit)
- input_tokens, output_tokens, cached_tokens
- model
- duration_ms
- response_text  (the model's final visible reply, concatenated from deltas)
- extras (free-form dict for tool-specific stuff)

If we can't extract cost, we raise `ParseError` with the raw text so the
harness can fail loudly rather than silently reporting $0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class ParseError(ValueError):
    """Raised when a parser cannot extract the data it needs."""

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


@dataclass
class ParsedToolOutput:
    tool: str
    native_cost_value: float = 0.0
    native_cost_unit: str = ""
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None
    model: Optional[str] = None
    duration_ms: Optional[int] = None
    response_text: str = ""
    extras: dict = field(default_factory=dict)
