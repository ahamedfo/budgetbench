"""Env-driven pricing calculator.

USD conversion rates come from environment variables first (loaded from
.env at the project root) and fall back to defaults in rates.yaml.
This way customers can update pricing without touching code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv


RATES_PATH = Path(__file__).resolve().parent / "rates.yaml"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_env_once():
    """Load .env from project root once per process."""
    if not getattr(_load_env_once, "_loaded", False):
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
        _load_env_once._loaded = True


_load_env_once()


@dataclass
class PricingResult:
    native_value: float
    native_unit: str
    usd_cost: float
    rate_source: str   # "env:VAR_NAME" or "rates.yaml" or "tool_reported"
    # Optional breakdown — populated when model-aware pricing is used
    # (currently Copilot: effective requests = raw × multiplier).
    effective_value: float | None = None
    multiplier: float | None = None
    model: str | None = None
    # Per-token rate breakdown (Copilot token-based pricing only) —
    # surfaced so the UI can show the actual `tokens × rate = USD` math.
    rate_breakdown: dict | None = None
    # USD-per-unit used (Bob only) — for the "Bobcoins × $0.50" math.
    usd_per_unit: float | None = None


class PricingError(ValueError):
    """Raised when we can't extract or convert cost."""


def _load_rates() -> dict:
    with open(RATES_PATH) as f:
        return yaml.safe_load(f)


def _resolve_usd_per_unit(tool: str, rates: dict) -> tuple[float, str]:
    """Return (usd_per_unit, source_label)."""
    cfg = rates[tool]
    env_var = cfg.get("usd_per_unit_env")
    if env_var:
        val = os.environ.get(env_var)
        if val is not None:
            try:
                return float(val), f"env:{env_var}"
            except ValueError:
                raise PricingError(
                    f"Env var {env_var} is not a valid float: {val!r}"
                )
    return float(cfg["usd_per_unit"]), "rates.yaml"


def compute_cost(
    tool: str,
    native_value: float,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cached_tokens: int | None = None,
    rates: dict | None = None,
) -> PricingResult:
    """Convert a tool's native cost to USD.

    Bob   : native_value is Bobcoins → multiply by BOB_USD_PER_BOBCOIN.
    Claude: native_value is already USD (the sum of all internal model
            usage Claude routes through).
    Copilot: per-model token rates (post-2026-06-01 GitHub billing model).
            cost = (input + output + cached) tokens × rate_per_mtok
            Each individual rate is env-overridable; see .env.example.
    """
    rates = rates or _load_rates()
    if tool not in rates:
        raise PricingError(f"Unknown tool: {tool}")

    if tool == "claude":
        return PricingResult(
            native_value=native_value,
            native_unit="usd",
            usd_cost=float(native_value),
            rate_source="tool_reported",
        )

    if tool == "copilot":
        return _compute_copilot_token_cost(
            rates["copilot"], model, input_tokens, output_tokens, cached_tokens, native_value
        )

    # Bob — simple usd_per_unit multiplication
    cfg = rates[tool]
    usd_per_unit, source = _resolve_usd_per_unit(tool, rates)
    return PricingResult(
        native_value=native_value,
        native_unit=cfg.get("native_unit", "unknown"),
        usd_cost=float(native_value) * usd_per_unit,
        rate_source=source,
        model=model,
        usd_per_unit=usd_per_unit,
    )


def _resolve_rate_per_field(rate_entry: dict, field: str) -> float:
    """Look up a single rate field, with env override if rate_entry has env_prefix."""
    base = float(rate_entry.get(field, 0.0))
    prefix = rate_entry.get("env_prefix")
    if not prefix:
        return base
    field_to_suffix = {
        "input_per_mtok": "_INPUT_PER_MTOK",
        "output_per_mtok": "_OUTPUT_PER_MTOK",
        "cached_per_mtok": "_CACHED_PER_MTOK",
    }
    env_var = prefix + field_to_suffix[field]
    val = os.environ.get(env_var)
    if val is None:
        return base
    try:
        return float(val)
    except ValueError:
        raise PricingError(f"Env var {env_var} not a valid float: {val!r}")


def _resolve_model_rate(cfg: dict, model: str | None) -> tuple[dict, str]:
    rates_table = cfg.get("model_rates") or {}
    if model:
        if model in rates_table:
            return rates_table[model], model
        lower = {k.lower(): k for k in rates_table.keys()}
        actual_key = lower.get(model.lower())
        if actual_key:
            return rates_table[actual_key], actual_key
    return cfg.get("default_model_rate") or {}, "default"


def _compute_copilot_token_cost(
    cfg: dict,
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cached_tokens: int | None,
    native_value: float,
) -> PricingResult:
    display_model = os.environ.get("COPILOT_DISPLAY_AS_MODEL")
    pricing_model = display_model.strip() if display_model else model

    rate, used_key = _resolve_model_rate(cfg, pricing_model)
    in_rate = _resolve_rate_per_field(rate, "input_per_mtok")
    out_rate = _resolve_rate_per_field(rate, "output_per_mtok")
    cache_rate = _resolve_rate_per_field(rate, "cached_per_mtok")

    in_cost  = (input_tokens  or 0) / 1_000_000 * in_rate
    out_cost = (output_tokens or 0) / 1_000_000 * out_rate
    ca_cost  = (cached_tokens or 0) / 1_000_000 * cache_rate
    total = in_cost + out_cost + ca_cost

    total_tokens = (input_tokens or 0) + (output_tokens or 0) + (cached_tokens or 0)
    rate_source = f"rates.yaml:{used_key}"
    if display_model and pricing_model != model:
        rate_source = f"rates.yaml:{used_key} (projected; actual model: {model})"

    return PricingResult(
        native_value=native_value,
        native_unit="token",
        usd_cost=total,
        rate_source=rate_source,
        effective_value=total_tokens,
        model=used_key,
        # Expose the per-token rates so the UI can render the math:
        #   input_tok × in_rate + output_tok × out_rate + cached_tok × cache_rate
        rate_breakdown={
            "input_per_mtok":  in_rate,
            "output_per_mtok": out_rate,
            "cached_per_mtok": cache_rate,
            "input_tokens":  input_tokens or 0,
            "output_tokens": output_tokens or 0,
            "cached_tokens": cached_tokens or 0,
        },
    )


def get_rate_summary() -> dict:
    """For display in the UI: what rates are currently in effect."""
    rates = _load_rates()
    out = {}
    for tool, cfg in rates.items():
        if tool == "claude":
            out[tool] = {"native_unit": "usd", "usd_per_unit": 1.0, "source": "tool_reported"}
        elif tool == "copilot":
            # Token-based — surface the default-model rate plus per-model rates
            default_rate = cfg.get("default_model_rate") or {}
            out[tool] = {
                "native_unit": "token",
                "default_rate": {
                    "input_per_mtok":  _resolve_rate_per_field(default_rate, "input_per_mtok"),
                    "output_per_mtok": _resolve_rate_per_field(default_rate, "output_per_mtok"),
                    "cached_per_mtok": _resolve_rate_per_field(default_rate, "cached_per_mtok"),
                },
                "source": "rates.yaml + env overrides",
            }
        else:
            # Bob and any future per-unit-priced tool
            usd_per_unit, source = _resolve_usd_per_unit(tool, rates)
            out[tool] = {
                "native_unit": cfg.get("native_unit"),
                "usd_per_unit": usd_per_unit,
                "source": source,
            }
    return out
