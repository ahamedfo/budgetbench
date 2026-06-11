"""Parse Claude Code's stdout in either --output-format json (single blob)
or --output-format stream-json (NDJSON event stream)."""
from __future__ import annotations

import json

from src.parsers import ParsedToolOutput, ParseError


def parse_claude_stdout(raw: str) -> ParsedToolOutput:
    """Detect single-blob json vs stream-json and route accordingly."""
    stripped = raw.strip()
    if not stripped:
        raise ParseError("Claude output is empty", raw=raw)

    # Stream-json: multiple JSON lines, first is typically type=system subtype=init.
    # Blob json: one big JSON object with type=result.
    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    if len(lines) > 1:
        return _parse_stream_json(raw)

    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        # Try to parse line-by-line as a fallback
        return _parse_stream_json(raw)

    return _from_result_event(obj, raw)


def _parse_stream_json(raw: str) -> ParsedToolOutput:
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not events:
        raise ParseError("Claude stream-json output had no parseable events", raw=raw)

    # Find the final 'result' event
    result = None
    for e in reversed(events):
        if e.get("type") == "result":
            result = e
            break
    if result is None:
        raise ParseError("Claude stream-json missing final 'result' event", raw=raw)

    # Concatenate assistant text deltas for response_text
    response_parts = []
    for e in events:
        if e.get("type") != "assistant":
            continue
        msg = e.get("message") or {}
        for chunk in msg.get("content") or []:
            if chunk.get("type") == "text":
                t = chunk.get("text", "")
                if t:
                    response_parts.append(t)
    # Join with double-newline so headers like `## VULNERABILITIES FOUND`
    # stay at line-start even when the preceding text part didn't end
    # in `\n`. (Empty `"".join` was glueing headers onto previous content,
    # which broke the regex-based section extractor.)
    response_text = "\n\n".join(response_parts).strip()

    return _from_result_event(result, raw, response_text_override=response_text)


def _from_result_event(result: dict, raw: str, response_text_override: str = "") -> ParsedToolOutput:
    if result.get("type") != "result":
        raise ParseError(f"Claude top-level JSON is not a result event: {result.get('type')!r}", raw=raw)

    cost = result.get("total_cost_usd")
    if cost is None:
        raise ParseError("Claude result event missing total_cost_usd", raw=raw)

    usage = result.get("usage") or {}
    # Claude breaks input into three buckets: fresh `input_tokens`,
    # `cache_creation_input_tokens` (new cache writes), and
    # `cache_read_input_tokens` (cache hits). The fresh number is tiny
    # for agentic runs because most prompt text comes from cache, so
    # showing only that figure (e.g. "38 input tokens") wildly under-
    # represents what Claude actually processed. We sum all three for
    # the displayed input total and keep the cache-read number separate
    # so the breakdown is available in extras.model_usage.
    fresh_in    = usage.get("input_tokens")               or 0
    cache_write = usage.get("cache_creation_input_tokens") or 0
    cache_read  = usage.get("cache_read_input_tokens")     or 0
    input_tokens  = fresh_in + cache_write + cache_read
    output_tokens = usage.get("output_tokens")
    cached_tokens = cache_read

    response_text = response_text_override or result.get("result") or ""

    # Try to pick the dominant model from modelUsage (highest cost wins)
    model_usage = result.get("modelUsage") or {}
    model = None
    if model_usage:
        model = max(model_usage.items(), key=lambda kv: kv[1].get("costUSD", 0))[0]

    extras = {
        "duration_api_ms": result.get("duration_api_ms"),
        "num_turns": result.get("num_turns"),
        "stop_reason": result.get("stop_reason"),
        "permission_denials": result.get("permission_denials") or [],
        "model_usage": model_usage,
        "session_id": result.get("session_id"),
    }

    return ParsedToolOutput(
        tool="claude",
        native_cost_value=float(cost),
        native_cost_unit="usd",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        model=model,
        duration_ms=result.get("duration_ms"),
        response_text=response_text,
        extras=extras,
    )
