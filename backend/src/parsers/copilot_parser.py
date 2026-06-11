"""Parse Copilot CLI's JSONL stream output (--output-format json).

Copilot's 'json' mode is actually JSONL — one object per line. Event
types observed (see RECON-FINDINGS.md):
- session.* events
- user.message
- assistant.turn_start, .turn_end
- assistant.reasoning_delta (ephemeral)
- assistant.message_start, .message_delta (ephemeral)
- assistant.message (final per-turn message with outputTokens)
- assistant.reasoning (final reasoning text)
- result (final event with usage stats)
"""
from __future__ import annotations

import json

from src.parsers import ParsedToolOutput, ParseError


def parse_copilot_stdout(raw: str) -> ParsedToolOutput:
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            # Non-JSON lines (banners, errors) — skip
            continue

    if not events:
        raise ParseError("Copilot output had no parseable JSONL events", raw=raw)

    # Find the final 'result' event
    result = None
    for e in reversed(events):
        if e.get("type") == "result":
            result = e
            break
    if result is None:
        # Could be an error before a result was emitted; surface it
        first_err = next((e for e in events if e.get("type") == "error"), None)
        if first_err:
            raise ParseError(
                f"Copilot failed before producing a result event: {first_err}",
                raw=raw,
            )
        raise ParseError("Copilot missing final 'result' event", raw=raw)

    usage = result.get("usage") or {}
    premium_requests = usage.get("premiumRequests")
    if premium_requests is None:
        raise ParseError("Copilot result event missing usage.premiumRequests", raw=raw)

    # Walk assistant.message events for model + output_tokens.
    # Copilot CLI 1.0.46 does NOT surface input or cached tokens, so we
    # estimate input by tallying everything visible that the model would
    # have re-read across turns: the user prompt, each tool-execution
    # result, and each prior assistant message. This is a lower bound on
    # actual input; real input is higher (system prompt, tool schemas,
    # plus the conversation re-sent every turn).
    model = None
    output_tokens = 0
    input_tokens = 0
    cached_tokens = 0
    response_parts = []
    num_turns = 0
    # Running tally of "context bytes" that the model has seen at least once
    visible_context_chars = 0
    # Each assistant turn re-reads everything before it; sum that across turns
    cumulative_input_chars = 0

    def _len_of(value) -> int:
        if value is None:
            return 0
        if isinstance(value, str):
            return len(value)
        if isinstance(value, (list, dict)):
            try:
                return len(json.dumps(value, ensure_ascii=False))
            except Exception:
                return 0
        return len(str(value))

    for e in events:
        t = e.get("type")
        data = e.get("data") or {}

        if t == "user.message":
            visible_context_chars += _len_of(data.get("transformedContent") or data.get("content"))

        elif t == "tool.execution_complete":
            # Tool results that came back to the model
            visible_context_chars += _len_of(data.get("result") or data.get("output"))

        elif t == "function":
            # Function/tool schema sent to the model
            visible_context_chars += _len_of(data)

        elif t == "assistant.turn_start":
            # At the start of each turn the model re-reads the whole context
            num_turns += 1
            cumulative_input_chars += visible_context_chars

        elif t == "assistant.message":
            if model is None:
                model = data.get("model")
            output_tokens += int(data.get("outputTokens") or 0)
            # Forward-compat: if Copilot ever surfaces these, prefer the real numbers
            input_tokens  += int(data.get("inputTokens")  or 0)
            cached_tokens += int(data.get("cachedInputTokens") or data.get("cachedTokens") or 0)
            content = data.get("content")
            if content:
                response_parts.append(content)
            # The reasoning + content this turn produced becomes input next turn
            visible_context_chars += _len_of(data.get("reasoningText"))
            visible_context_chars += _len_of(content)

    # Note `\n\n` separator below so per-turn responses don't get glued together

    # If Copilot CLI didn't expose input tokens, estimate from visible context.
    # ~4 chars/token (English) + a fixed 4000-token allowance for the
    # system prompt + tool schemas the model sees every turn.
    estimated_input_tokens = None
    if not input_tokens:
        SYSTEM_PROMPT_OVERHEAD = 4000  # tokens per turn for system + tool defs
        estimated_input_tokens = (
            cumulative_input_chars // 4
            + SYSTEM_PROMPT_OVERHEAD * max(num_turns, 1)
        )
        input_tokens = estimated_input_tokens

    if model is None:
        for e in events:
            if e.get("type") == "session.tools_updated":
                model = (e.get("data") or {}).get("model")
                if model:
                    break

    # Detect a session.error with errorType=rate_limit (Copilot Free
    # 5-hour window exhaustion is the common case). Surface it in extras
    # so the UI can render a hover-warning on the column badge.
    session_error = None
    for e in events:
        if e.get("type") == "session.error":
            d = e.get("data") or {}
            session_error = {
                "type": d.get("errorType") or "unknown",
                "code": d.get("errorCode"),
                "message": d.get("message") or "Copilot session error",
                "status_code": d.get("statusCode"),
            }
            break

    extras = {
        "session_id": result.get("sessionId"),
        "exit_code": result.get("exitCode"),
        "total_api_duration_ms": usage.get("totalApiDurationMs"),
        "session_duration_ms": usage.get("sessionDurationMs"),
        "code_changes": usage.get("codeChanges") or {},
        "event_count": len(events),
        "premium_requests": premium_requests,
        "turns": num_turns,
        # Be honest about input tokens — if Copilot CLI didn't surface them,
        # the value here is our estimate from visible JSONL content.
        "input_tokens_estimated": estimated_input_tokens is not None,
        "session_error": session_error,
    }

    # native_cost_value is informational only — actual billing is token-based.
    # We surface premiumRequests as the native value for legacy display
    # but Copilot's USD cost is computed from tokens × per-model rates.
    return ParsedToolOutput(
        tool="copilot",
        native_cost_value=float(premium_requests),
        native_cost_unit="premium_request",
        input_tokens=input_tokens or None,
        output_tokens=output_tokens or None,
        cached_tokens=cached_tokens or None,
        model=model,
        duration_ms=usage.get("sessionDurationMs"),
        response_text="\n\n".join(response_parts).strip(),
        extras=extras,
    )
