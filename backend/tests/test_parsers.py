from pathlib import Path

import pytest

from src.parsers import ParseError
from src.parsers.bob_parser import parse_bob_stdout
from src.parsers.claude_parser import parse_claude_stdout
from src.parsers.copilot_parser import parse_copilot_stdout


FIXTURES = Path(__file__).parent / "fixtures"


# ---------- Bob ----------

def test_bob_blob_json_pong_fixture():
    raw = (FIXTURES / "bob_json.out").read_text()
    out = parse_bob_stdout(raw)
    assert out.tool == "bob"
    assert out.native_cost_unit == "bobcoin"
    assert out.native_cost_value > 0
    assert out.input_tokens == 34890
    assert out.output_tokens == 32
    assert out.cached_tokens == 17402


def test_bob_stream_json_pong_fixture():
    raw = (FIXTURES / "bob_stream.out").read_text()
    out = parse_bob_stdout(raw)
    assert out.tool == "bob"
    assert out.native_cost_unit == "bobcoin"
    assert out.native_cost_value > 0
    assert "PONG" in out.response_text
    assert out.model == "premium"


def test_bob_parse_error_on_garbage():
    with pytest.raises(ParseError):
        parse_bob_stdout("not json at all, just words")


def test_bob_parse_error_on_missing_stats():
    with pytest.raises(ParseError):
        parse_bob_stdout('{"response": "ok"}')


def test_bob_attempt_completion_extracts_structured_response():
    """Bob carries its final ## sections inside tool_use:attempt_completion
    rather than streaming message deltas — verify the parser pulls them out."""
    stream = "\n".join([
        '{"type":"init","timestamp":"t","session_id":"s","model":"premium"}',
        '{"type":"message","role":"user","content":"do work"}',
        '{"type":"message","role":"assistant","content":"<thinking>","delta":true}',
        '{"type":"message","role":"assistant","content":"working...","delta":true}',
        '{"type":"tool_use","tool_name":"attempt_completion","tool_id":"tool-1",'
            '"parameters":{"result":"## VULNERABILITIES FOUND\\nSQLi.\\n\\n## FIXES APPLIED\\nFix.\\n\\n## TESTS ADDED\\nT.\\n\\n## TEST RESULTS\\n29 passed"}}',
        '{"type":"result","status":"success","stats":{"session_costs":0.5,"budget_spend":1,"max_budget":500,"tool_calls":1,"input_tokens":100,"output_tokens":50,"duration_ms":1000}}',
    ])
    out = parse_bob_stdout(stream)
    assert "VULNERABILITIES FOUND" in out.response_text
    assert "29 passed" in out.response_text


# ---------- Claude ----------

def test_claude_blob_json_pong_fixture():
    raw = (FIXTURES / "claude_json.out").read_text()
    out = parse_claude_stdout(raw)
    assert out.tool == "claude"
    assert out.native_cost_unit == "usd"
    assert out.native_cost_value > 0
    # input_tokens is now the SUM of fresh input + cache_creation +
    # cache_read (Claude's full input picture). PONG fixture:
    #   6 fresh + 10773 cache_creation + 17473 cache_read = 28252
    assert out.input_tokens == 6 + 10773 + 17473
    assert out.output_tokens == 7
    assert out.cached_tokens == 17473
    assert "PONG" in out.response_text or out.response_text == ""


def test_claude_stream_json_pong_fixture():
    raw = (FIXTURES / "claude_stream.out").read_text()
    out = parse_claude_stdout(raw)
    assert out.tool == "claude"
    assert out.native_cost_unit == "usd"
    assert "PONG" in out.response_text


def test_claude_parse_error_on_no_result_event():
    raw = '{"type":"system","subtype":"init"}\n'
    with pytest.raises(ParseError):
        parse_claude_stdout(raw)


# ---------- Copilot ----------

def test_copilot_json_pong_fixture():
    raw = (FIXTURES / "copilot_json.out").read_text()
    out = parse_copilot_stdout(raw)
    assert out.tool == "copilot"
    assert out.native_cost_unit == "premium_request"
    assert out.native_cost_value >= 1
    assert "PONG" in out.response_text
    assert out.model is not None
    assert "claude" in out.model.lower() or "gpt" in out.model.lower()


def test_copilot_parse_error_on_no_events():
    with pytest.raises(ParseError):
        parse_copilot_stdout("Error: not authenticated\n")


def test_copilot_parse_error_on_missing_premium_requests():
    raw = '{"type":"result","usage":{}}\n'
    with pytest.raises(ParseError):
        parse_copilot_stdout(raw)
