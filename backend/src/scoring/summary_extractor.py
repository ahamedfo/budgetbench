"""Extract the four ## sections (VULNERABILITIES FOUND / FIXES APPLIED /
TESTS ADDED / TEST RESULTS) from a tool's response text.

The prompt asks every tool to end its response with these exact markdown
headers. Tools comply unevenly — sometimes the header is missing, sometimes
the spacing or capitalization varies. We handle that gracefully.
"""
from __future__ import annotations

import re

from src.models.run_result import ToolSummary


# Each section accepts several common variants — vulnerability scenarios
# typically use VULNERABILITIES FOUND / FIXES APPLIED, generic ones use
# TASK SUMMARY / CODE CHANGES. Both parse into the same internal fields
# so the UI stays consistent. Optional second-word groups use horizontal
# whitespace [ \t] (not \s) so we don't accidentally consume the newline
# that ends the header line.
SECTIONS = [
    ("vulnerabilities_found",
        r"(?:VULNERABILIT(?:IES|Y)|ISSUES?|FINDINGS?|PROBLEMS?|ANALYSIS|TASK)"
        r"(?:[ \t]+(?:FOUND|IDENTIFIED|DETECTED|SUMMARY|COMPLETED))?"),
    ("fixes_applied",
        r"(?:FIXE?S?|CHANGES?|CODE[ \t]+CHANGES?|MODIFICATIONS?|OPTIMIZATIONS?|REFACTORS?)"
        r"(?:[ \t]+(?:APPLIED|MADE|IMPLEMENTED))?"),
    ("tests_added",
        r"(?:NEW[ \t]+)?TESTS?[ \t]+(?:ADDED|CREATED|WRITTEN)"),
    ("test_results",
        r"TEST[ \t]+RESULTS?"),
]


def extract_sections(text: str) -> ToolSummary:
    """Pull each ## section's body. Tolerant of case, spacing, and trailing-
    text variants in the header line (e.g., `## FIXES APPLIED (2)`)."""
    summary = ToolSummary()
    found = {}

    if not text:
        for key, _ in SECTIONS:
            found[key] = False
        summary.raw_section_found = found
        return summary

    for key, pattern in SECTIONS:
        # Header: 1-4 '#' chars, the section name, optional trailing text
        # on the same line. Body: everything until the next markdown-style
        # header or end of text.
        rx = re.compile(
            rf"^\s*#{{1,4}}\s*{pattern}[^\n]*\n(.*?)(?=^\s*#{{1,4}}\s+\S|\Z)",
            re.IGNORECASE | re.MULTILINE | re.DOTALL,
        )
        m = rx.search(text)
        if m:
            body = m.group(1).strip()
            setattr(summary, key, body)
            found[key] = bool(body)
        else:
            found[key] = False

    summary.raw_section_found = found
    return summary


def section_completeness(summary: ToolSummary) -> float:
    """Return [0, 1] — fraction of the four sections present."""
    flags = summary.raw_section_found or {}
    if not flags:
        return 0.0
    return sum(1 for v in flags.values() if v) / max(len(flags), 1)
