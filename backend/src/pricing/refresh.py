"""Live pricing refresh (stub).

The harness reads model rates from src/pricing/rates.yaml. To keep
those rates current automatically, plug a fetcher in here.

Current state: this is a stub that returns the in-file rates as-is.
When a real pricing API or page-scraper is wired up, replace
`fetch_latest_rates()` with the real implementation and the
`refresh()` function will overwrite rates.yaml on disk.

Idempotent: safe to call from cron or `./bakeoff refresh-pricing`.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml


RATES_PATH = Path(__file__).resolve().parent / "rates.yaml"


def fetch_latest_rates() -> dict | None:
    """Return a dict shaped like rates.yaml, or None if no fetcher is configured.

    Replace this body with calls to:
      - Anthropic public pricing page
      - OpenAI public pricing page
      - GitHub Copilot AI-Credits docs
    and merge into the rates.yaml schema.
    """
    return None


def refresh() -> tuple[bool, str]:
    """Refresh rates.yaml in place. Returns (changed, message)."""
    new_rates = fetch_latest_rates()
    if new_rates is None:
        return False, (
            "No live-pricing fetcher configured. Edit "
            "src/pricing/refresh.py:fetch_latest_rates() to add one, "
            "or edit rates.yaml manually."
        )

    current = yaml.safe_load(RATES_PATH.read_text())
    if current == new_rates:
        return False, "rates.yaml already up to date"

    # Back up before overwriting
    shutil.copyfile(RATES_PATH, RATES_PATH.with_suffix(".yaml.bak"))
    RATES_PATH.write_text(yaml.safe_dump(new_rates, sort_keys=False))
    return True, f"Updated {RATES_PATH} (previous saved to rates.yaml.bak)"
