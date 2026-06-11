from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class ToolSummary:
    """Parsed ## section content from the tool's own self-report."""
    vulnerabilities_found: str = ""
    fixes_applied: str = ""
    tests_added: str = ""
    test_results: str = ""
    raw_section_found: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerificationResult:
    """Objective verification of what the tool actually did."""
    tests_total: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    new_tests_added: int = 0
    semgrep_findings_total: int = 0
    semgrep_findings_high: int = 0
    semgrep_findings_medium: int = 0
    # Semgrep is OPTIONAL per scenario. semgrep_ran tells the UI whether
    # to show the findings row at all (vs. "—") for non-security scenarios.
    semgrep_ran: bool = False
    semgrep_config_used: str | None = None
    # Whether the scenario declared forbidden_patterns at all. If False,
    # the UI shows "not configured" instead of conflating with a "✓ clean"
    # verdict for non-vulnerability scenarios.
    forbidden_patterns_configured: bool = False
    vuln_pattern_still_present: bool = True
    verify_sh_exit_code: int = -1
    verify_sh_passed: bool = False
    lines_changed: int = 0
    files_modified: list[str] = field(default_factory=list)
    # Unified-diff text between original and working_copy, with vendored
    # / tool-scratchpad dirs filtered out. Used by the UI to show side-by-
    # side "what each tool actually changed". Truncated to a sane limit
    # so a runaway diff can't blow up the DB or the SSE payload.
    diff_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RunResult:
    """Everything we know about a single tool's run against a scenario."""
    tool: str
    scenario_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    wall_clock_ms: int = 0
    exit_code: int = -1
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None
    working_copy_path: Optional[str] = None

    # Tool-native cost data
    native_cost_value: float = 0.0
    native_cost_unit: str = ""

    # Normalized cost
    usd_cost: float = 0.0

    # Tokens
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None

    # Model used
    model: Optional[str] = None

    # Per-tool extras (free-form JSON-serializable dict for tool-specific stuff)
    extras: dict = field(default_factory=dict)

    # Summary + verification populated post-run
    summary: Optional[ToolSummary] = None
    verification: Optional[VerificationResult] = None

    error: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["started_at"] = self.started_at.isoformat() if self.started_at else None
        d["completed_at"] = self.completed_at.isoformat() if self.completed_at else None
        return d
