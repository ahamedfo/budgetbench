"""Parse Bob's stdout in either --output-format json (single blob) or
--output-format stream-json (NDJSON event stream)."""
from __future__ import annotations

import json
import re

from src.parsers import ParsedToolOutput, ParseError


YOLO_BANNER = re.compile(r"^YOLO mode is enabled\.\s*", re.MULTILINE)
TEXT_DUMP_DELIM = re.compile(r"^---output---\s*$", re.MULTILINE)
# Bob CLI prints "Cost: 0.85" inside message events when summarizing an
# attempt_completion. Used as a last-resort fallback when the stream
# ends before the terminal `result` event fires (which carries the
# authoritative stats).
COST_FALLBACK = re.compile(r"Cost:\s*([0-9]+(?:\.[0-9]+)?)")


def _strip_preamble(raw: str) -> str:
    return YOLO_BANNER.sub("", raw).lstrip()


def _fallback_cost_from_messages(events: list) -> float:
    """Last-ditch cost extraction: scan all assistant messages for the
    'Cost: N.NN' pattern Bob's CLI emits alongside attempt_completion.
    Returns 0.0 if nothing matches (so the run still surfaces, just
    with no cost data)."""
    for e in events:
        if e.get("type") not in ("message", "tool_use"):
            continue
        text = e.get("content") or ""
        m = COST_FALLBACK.search(text)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return 0.0


def _fallback_stats_from_events(events: list) -> dict:
    """Reconstruct what we can of the stats dict from the raw event
    stream when the terminal `result` event is missing.
        • duration_ms   first → last event timestamp delta
        • tool_calls    count of tool_use events
    Tokens stay None — Bob doesn't emit per-event token counts."""
    from datetime import datetime
    stats = {"tool_calls": sum(1 for e in events if e.get("type") == "tool_use")}

    timestamps = []
    for e in events:
        ts = e.get("timestamp")
        if not ts:
            continue
        try:
            timestamps.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
        except ValueError:
            continue
    if len(timestamps) >= 2:
        stats["duration_ms"] = int((max(timestamps) - min(timestamps)).total_seconds() * 1000)
    return stats


def parse_bob_stdout(raw: str) -> ParsedToolOutput:
    """Auto-detects single-blob JSON vs NDJSON stream and routes.

    Strategy: count lines that are standalone parseable JSON objects.
    NDJSON stream-json has 2+. Blob has 0 (it's pretty-printed across
    many lines so no individual line parses by itself, except `{}` and
    `}`).
    """
    json_lines = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line or not line.startswith("{") or not line.endswith("}"):
            continue
        try:
            json.loads(line)
            json_lines += 1
            if json_lines >= 2:
                return _parse_stream_json(raw)
        except json.JSONDecodeError:
            continue

    return _parse_blob_json(_strip_preamble(raw), raw)


def _parse_blob_json(stripped: str, raw: str) -> ParsedToolOutput:
    # In --output-format json mode bob prints a text "---output---PONG---output---"
    # block before the JSON. Strip it.
    if "---output---" in stripped:
        chunks = TEXT_DUMP_DELIM.split(stripped)
        # The trailing chunk is the JSON envelope
        json_text = chunks[-1].strip()
        # The middle chunks form the response text
        response_text = "\n".join(c.strip() for c in chunks[1:-1] if c.strip())
    else:
        json_text = stripped.strip()
        response_text = ""

    try:
        envelope = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise ParseError(f"Bob JSON envelope unparseable: {e}", raw=raw)

    stats = envelope.get("stats") or {}
    if not stats:
        raise ParseError("Bob output missing 'stats' block", raw=raw)

    # Cost: stats.sessionCost in --output-format json
    cost = stats.get("sessionCost")
    if cost is None:
        cost = stats.get("session_costs")  # rare fallback
    if cost is None:
        raise ParseError("Bob output missing sessionCost in stats", raw=raw)

    # Tokens — premium tier model
    models = stats.get("models") or {}
    tokens = (models.get("premium") or {}).get("tokens") or {}
    input_tokens = tokens.get("prompt")
    output_tokens = tokens.get("candidates")
    cached_tokens = tokens.get("cached")

    api = (models.get("premium") or {}).get("api") or {}
    duration_ms = api.get("totalLatencyMs")

    extras = {
        "model_tier": list(models.keys()),
        "tool_calls": (stats.get("tools") or {}).get("totalCalls"),
        "lines_added": (stats.get("files") or {}).get("totalLinesAdded"),
        "lines_removed": (stats.get("files") or {}).get("totalLinesRemoved"),
        "budget_spend": stats.get("budgetSpend"),
        "max_budget": stats.get("maxBudget"),
    }
    if envelope.get("response"):
        # In bob's json mode 'response' is often empty (it's in the text dump)
        response_text = envelope["response"]

    return ParsedToolOutput(
        tool="bob",
        native_cost_value=float(cost),
        native_cost_unit="bobcoin",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        model="premium",
        duration_ms=duration_ms,
        response_text=response_text,
        extras=extras,
    )


def _parse_stream_json(raw: str) -> ParsedToolOutput:
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            # Tolerate non-JSON banner lines that snuck through
            continue

    if not events:
        raise ParseError("Bob stream-json output contained no parseable events", raw=raw)

    # Find the final 'result' event (it carries cost stats).
    final = None
    for e in reversed(events):
        if e.get("type") == "result":
            final = e
            break

    # Bob's final structured response (the ## sections we ask for in the
    # prompt) is carried inside a `tool_use` event with
    # tool_name=attempt_completion → parameters.result. Streaming
    # assistant `message` events with delta=true contain the in-progress
    # text (often <thinking> content), which is not what we want for the
    # summary extractor. Use attempt_completion if present; otherwise
    # fall back to concatenated message deltas.
    attempt_results = [
        (e.get("parameters") or {}).get("result", "")
        for e in events
        if e.get("type") == "tool_use" and e.get("tool_name") == "attempt_completion"
    ]
    if attempt_results:
        response_text = "\n\n".join(r for r in attempt_results if r).strip()
    else:
        response_parts = [
            e.get("content", "")
            for e in events
            if e.get("type") == "message"
            and e.get("role") == "assistant"
            and e.get("delta")
        ]
        response_text = "".join(response_parts).strip()

    parse_warning = None
    if final is None:
        # Bob's CLI sometimes ends the stream right after attempt_completion
        # without emitting the terminal `result` event with cost stats. As
        # long as we got the attempt_completion payload, the work itself
        # was reported — we just don't have authoritative cost/token data.
        # Recover what we can from the in-stream events:
        #   • cost      → "Cost: N.NN" pattern in messages near attempt_completion
        #   • duration  → time delta between first and last event timestamps
        #   • tool_calls → count of tool_use events
        # Mark with a warning and continue rather than failing the run.
        if not attempt_results:
            raise ParseError("Bob stream-json missing final 'result' event", raw=raw)
        cost = _fallback_cost_from_messages(events)
        stats = _fallback_stats_from_events(events)
        parse_warning = (
            "Bob stream ended without terminal result event; cost/tokens recovered "
            "from message logs (may be incomplete)."
        )
    else:
        stats = final.get("stats") or {}
        cost = stats.get("session_costs", stats.get("sessionCost"))
        if cost is None:
            raise ParseError("Bob stream-json result event missing session_costs", raw=raw)

    model = None
    for e in events:
        if e.get("type") == "init":
            model = e.get("model")
            break

    extras = {
        "tool_calls": stats.get("tool_calls"),
        "budget_spend": stats.get("budget_spend"),
        "max_budget": stats.get("max_budget"),
    }
    if parse_warning:
        extras["parse_warning"] = parse_warning

    return ParsedToolOutput(
        tool="bob",
        native_cost_value=float(cost),
        native_cost_unit="bobcoin",
        input_tokens=stats.get("input_tokens"),
        output_tokens=stats.get("output_tokens"),
        cached_tokens=None,
        model=model,
        duration_ms=stats.get("duration_ms"),
        response_text=response_text,
        extras=extras,
    )
