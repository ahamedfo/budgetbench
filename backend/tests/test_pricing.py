import pytest

from src.pricing.calculator import (
    PricingError,
    PricingResult,
    compute_cost,
    get_rate_summary,
)


@pytest.fixture(autouse=True)
def clear_copilot_projection(monkeypatch):
    """Ensure no .env-loaded COPILOT_DISPLAY_AS_MODEL leaks into tests
    that assume the actual model is what's priced."""
    monkeypatch.delenv("COPILOT_DISPLAY_AS_MODEL", raising=False)


def test_bob_native_to_usd_default():
    # Default: 1 Bobcoin = $0.50
    r = compute_cost("bob", 0.5)
    assert isinstance(r, PricingResult)
    assert r.native_unit == "bobcoin"
    assert r.native_value == 0.5
    assert r.usd_cost == pytest.approx(0.25)


def test_bob_usd_per_bobcoin_env_override(monkeypatch):
    monkeypatch.setenv("BOB_USD_PER_BOBCOIN", "0.75")
    r = compute_cost("bob", 2)
    assert r.usd_cost == pytest.approx(1.5)
    assert r.rate_source == "env:BOB_USD_PER_BOBCOIN"


def test_claude_passthrough_usd():
    r = compute_cost("claude", 0.0876)
    assert r.usd_cost == pytest.approx(0.0876)
    assert r.native_unit == "usd"
    assert r.rate_source == "tool_reported"


def test_copilot_token_cost_haiku():
    # Haiku 4.5: input $0.80/MTok, output $4.00/MTok, cached $0.08/MTok
    # 1M input, 100k output, 0 cached → $0.80 + $0.40 = $1.20
    r = compute_cost(
        "copilot", native_value=1, model="claude-haiku-4.5",
        input_tokens=1_000_000, output_tokens=100_000, cached_tokens=0,
    )
    assert r.native_unit == "token"
    assert r.usd_cost == pytest.approx(1.20)
    assert r.effective_value == 1_100_000
    assert r.model == "claude-haiku-4.5"


def test_copilot_token_cost_sonnet():
    # Sonnet 4.5: input $3, output $15, cached $0.30
    # 10k input, 5k output, 1k cached → 0.03 + 0.075 + 0.0003 = $0.1053
    r = compute_cost(
        "copilot", native_value=2, model="claude-sonnet-4.5",
        input_tokens=10_000, output_tokens=5_000, cached_tokens=1_000,
    )
    assert r.usd_cost == pytest.approx(0.1053)


def test_copilot_token_cost_zero_rate_model():
    # GPT-4.1 is $0/MTok across the board on paid plans → free
    r = compute_cost(
        "copilot", native_value=1, model="gpt-4.1",
        input_tokens=100_000, output_tokens=50_000,
    )
    assert r.usd_cost == pytest.approx(0.0)


def test_copilot_unknown_model_falls_back_to_default_rate():
    # default_model_rate is 1.25/10.00/0.125
    # 1M input only → $1.25
    r = compute_cost(
        "copilot", native_value=1, model="totally-fake-model-xyz",
        input_tokens=1_000_000, output_tokens=0,
    )
    assert r.usd_cost == pytest.approx(1.25)
    assert "default" in r.rate_source


def test_copilot_no_tokens_returns_zero():
    # With no tokens captured, cost is $0 (output-only-or-empty case)
    r = compute_cost("copilot", native_value=1, model="claude-haiku-4.5")
    assert r.usd_cost == pytest.approx(0.0)
    assert r.effective_value == 0


def test_copilot_env_override_for_specific_rate(monkeypatch):
    monkeypatch.setenv("COPILOT_RATE_CLAUDE_SONNET_4_5_OUTPUT_PER_MTOK", "20.00")
    # 1k output × $20/MTok = $0.02
    r = compute_cost(
        "copilot", native_value=1, model="claude-sonnet-4.5",
        input_tokens=0, output_tokens=1_000,
    )
    assert r.usd_cost == pytest.approx(0.02)


def test_copilot_env_override_default_rate(monkeypatch):
    monkeypatch.setenv("COPILOT_RATE_DEFAULT_INPUT_PER_MTOK", "99.00")
    r = compute_cost(
        "copilot", native_value=1, model="unknown-model",
        input_tokens=1_000_000, output_tokens=0,
    )
    assert r.usd_cost == pytest.approx(99.00)


def test_copilot_display_as_model_projection(monkeypatch):
    """Run executes on Haiku but UI prices it as if it were Sonnet."""
    monkeypatch.setenv("COPILOT_DISPLAY_AS_MODEL", "claude-sonnet-4.5")
    # Reuse the existing Copilot run tokens — 339,619 in / 8,468 out
    r = compute_cost(
        "copilot", native_value=1, model="claude-haiku-4.5",
        input_tokens=339_619, output_tokens=8_468, cached_tokens=0,
    )
    # Sonnet 4.5: $3.00 input + $15.00 output per MTok
    expected = 339_619 / 1_000_000 * 3.00 + 8_468 / 1_000_000 * 15.00
    assert r.usd_cost == pytest.approx(expected, rel=1e-4)
    assert r.usd_cost == pytest.approx(1.1459, rel=1e-3)
    # The rate_source should make the projection obvious
    assert "projected" in r.rate_source
    assert "claude-haiku-4.5" in r.rate_source  # actual model named in source
    assert r.model == "claude-sonnet-4.5"        # what we priced it as


def test_copilot_no_display_override_uses_actual_model(monkeypatch):
    monkeypatch.delenv("COPILOT_DISPLAY_AS_MODEL", raising=False)
    r = compute_cost(
        "copilot", native_value=1, model="claude-haiku-4.5",
        input_tokens=339_619, output_tokens=8_468,
    )
    # Haiku: $0.80 in + $4.00 out
    expected = 339_619 / 1_000_000 * 0.80 + 8_468 / 1_000_000 * 4.00
    assert r.usd_cost == pytest.approx(expected, rel=1e-4)
    assert "projected" not in r.rate_source
    assert r.model == "claude-haiku-4.5"


def test_unknown_tool_raises():
    with pytest.raises(PricingError):
        compute_cost("nonexistent", 1.0)


def test_invalid_env_value_raises(monkeypatch):
    monkeypatch.setenv("BOB_USD_PER_BOBCOIN", "not-a-number")
    with pytest.raises(PricingError):
        compute_cost("bob", 1)


def test_get_rate_summary_returns_all_tools():
    summary = get_rate_summary()
    assert set(summary.keys()) == {"bob", "claude", "copilot"}
    assert summary["claude"]["native_unit"] == "usd"
    assert summary["bob"]["usd_per_unit"] > 0
