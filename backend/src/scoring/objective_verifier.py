"""Objective verifier: run pytest + semgrep + diff against a working copy
and return a structured `VerificationResult`. No LLM judgment involved."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from src.models.run_result import VerificationResult


# Use the same Python the harness was installed with — the working copy
# may not have a venv of its own when each tool is done with it.
HARNESS_PYTHON = Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python"
HARNESS_SEMGREP = Path(__file__).resolve().parents[2] / ".venv" / "bin" / "semgrep"


def verify(
    working_copy: Path,
    original_snapshot: Path | None = None,
    forbidden_patterns: list[str] | None = None,
    semgrep_config: str | None = None,
    verify_sh: Path | None = None,
) -> VerificationResult:
    """Run all objective checks on a tool's working copy.

    Args:
        working_copy: path to the tool's modified copy of the scenario repo
        original_snapshot: path to the pristine copy (for diff)
        forbidden_patterns: regex strings that MUST NOT appear post-fix
        semgrep_config: ruleset to apply
        verify_sh: optional scenario-specific binary pass/fail script
    """
    # Resolve to absolute — subprocess flags like --rootdir need absolute paths.
    working_copy = Path(working_copy).resolve()
    if original_snapshot is not None:
        original_snapshot = Path(original_snapshot).resolve()
    result = VerificationResult()

    # --- pytest ---
    tests_total, tests_passed, tests_failed = _run_pytest(working_copy)
    result.tests_total = tests_total
    result.tests_passed = tests_passed
    result.tests_failed = tests_failed

    # --- new tests added (diff against original) ---
    if original_snapshot and original_snapshot.exists():
        result.new_tests_added = _count_new_tests(working_copy, original_snapshot)
        result.lines_changed, result.files_modified = _diff_lines(
            working_copy, original_snapshot
        )
        result.diff_text = _diff_text(working_copy, original_snapshot)

    # --- semgrep (optional — only runs if the scenario set a config) ---
    if semgrep_config:
        findings_total, by_severity = _run_semgrep(working_copy, semgrep_config)
        result.semgrep_findings_total = findings_total
        result.semgrep_findings_high = by_severity.get("ERROR", 0)
        result.semgrep_findings_medium = by_severity.get("WARNING", 0)
        result.semgrep_ran = True
        result.semgrep_config_used = semgrep_config
    else:
        # Not a security scenario — skip semgrep entirely
        result.semgrep_ran = False

    # --- forbidden pattern grep (optional per scenario) ---
    if forbidden_patterns:
        result.forbidden_patterns_configured = True
        result.vuln_pattern_still_present = _any_forbidden_present(
            working_copy, forbidden_patterns
        )
    else:
        result.forbidden_patterns_configured = False
        # Default to "clean" — no patterns to match means no failure mode here
        result.vuln_pattern_still_present = False

    # --- verify.sh ---
    if verify_sh and verify_sh.exists():
        ec = _run_verify_sh(working_copy, verify_sh)
        result.verify_sh_exit_code = ec
        result.verify_sh_passed = ec == 0

    return result


def _run_pytest(working_copy: Path) -> tuple[int, int, int]:
    """Run pytest inside the working copy.

    The scenario repo carries its own minimal pyproject.toml so pytest
    anchors on the working_copy (not the harness root). We also ignore
    common vendored dirs so pytest doesn't crawl into Claude/Bob/Copilot's
    own .venv that they may have created.
    """
    py = str(HARNESS_PYTHON) if HARNESS_PYTHON.exists() else "python"
    ignores = []
    for d in EXCLUDED_DIRS:
        ignores.extend(["--ignore-glob", f"**/{d}/**"])
    try:
        proc = subprocess.run(
            # No -q here — the scenario's pyproject.toml may already set -q via
            # addopts; combining -q with -q sometimes suppresses the summary line.
            [py, "-m", "pytest", "--tb=no", "-p", "no:cacheprovider",
             "-o", "addopts=",                # nuke any pre-existing addopts
             "--rootdir", str(working_copy), *ignores],
            cwd=working_copy,
            capture_output=True,
            text=True,
            timeout=300,
        )
        out = proc.stdout + proc.stderr
        passed = 0
        failed = 0
        m_pass = re.search(r"(\d+) passed", out)
        if m_pass:
            passed = int(m_pass.group(1))
        m_fail = re.search(r"(\d+) failed", out)
        if m_fail:
            failed = int(m_fail.group(1))
        return passed + failed, passed, failed
    except subprocess.TimeoutExpired:
        return 0, 0, 0
    except FileNotFoundError:
        return 0, 0, 0


# Directories we never count toward "lines changed" or "new tests".
# `.bob` / `.claude` / `.copilot` are scratchpads the agent CLIs create
# inside their own working dir (e.g., `.bob/notes/pending-notes.txt`
# tracks which files the agent edited) — they are agent runtime state,
# not code changes.
EXCLUDED_DIRS = {".venv", "venv", "env", "__pycache__", ".git", ".pytest_cache",
                 ".mypy_cache", "node_modules", ".tox", "dist", "build", "instance",
                 ".bob", ".claude", ".copilot"}


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


def _count_new_tests(working_copy: Path, original: Path) -> int:
    new_count = 0
    test_dirs = []
    if (working_copy / "tests").exists():
        test_dirs.append(working_copy / "tests")
    # Also scan top-level test_*.py
    for f in working_copy.iterdir():
        if f.is_file() and f.name.startswith("test_") and f.suffix == ".py":
            test_dirs.append(f.parent)
            break

    for test_dir in test_dirs:
        for f in test_dir.rglob("test_*.py"):
            if _is_excluded(f.relative_to(working_copy)):
                continue
            rel = f.relative_to(working_copy)
            orig_file = original / rel
            if not orig_file.exists():
                new_count += len(re.findall(r"^\s*def\s+test_", f.read_text(errors="ignore"), re.M))
                continue
            cur_tests = set(re.findall(r"^\s*def\s+(test_\w+)", f.read_text(errors="ignore"), re.M))
            orig_tests = set(re.findall(r"^\s*def\s+(test_\w+)", orig_file.read_text(errors="ignore"), re.M))
            new_count += len(cur_tests - orig_tests)
    return new_count


# Cap the per-tool diff payload so a runaway agent (e.g., reformatting
# 5000 lines) can't blow up the SSE message or the runs.db row.
MAX_DIFF_BYTES = 64 * 1024


def _diff_text(working_copy: Path, original: Path) -> str:
    """git diff --no-index unified patch between original and working_copy,
    with vendored / tool-scratchpad dirs filtered out, paths rewritten to
    be relative ('a/<file>', 'b/<file>'), and truncated to MAX_DIFF_BYTES.

    Returned as a single string, ready to drop into a <pre> in the UI."""
    try:
        # --no-prefix strips git's default a/b/ prefixes so we can substitute
        # our own absolute → relative path rewrite cleanly below.
        # -U6 gives 6 lines of surrounding context per hunk (vs git's default
        # of 3) so the audience can see the broader "before vs after" code,
        # not just the changed line.
        proc = subprocess.run(
            ["git", "diff", "--no-index", "--no-color", "--no-prefix",
             "-U6", str(original), str(working_copy)],
            capture_output=True, text=True, timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""

    raw = proc.stdout
    if not raw:
        return ""

    # Split into per-file hunks. Each starts at a `diff --git ...` line
    # (or `diff` line for --no-index). We filter at this level so an
    # excluded file is dropped completely, not partially.
    out_chunks: list[str] = []
    current: list[str] = []
    keep_current = True
    orig_str = str(original)
    work_str = str(working_copy)

    def flush():
        if keep_current and current:
            out_chunks.append("".join(current))

    for line in raw.splitlines(keepends=True):
        if line.startswith("diff --git") or line.startswith("diff "):
            flush()
            current = [line]
            # Decide keep/drop based on the path in this header line
            keep_current = not any(
                f"/{d}/" in line or line.rstrip().endswith(f"/{d}")
                for d in EXCLUDED_DIRS
            )
            continue
        current.append(line)
    flush()

    cleaned = "".join(out_chunks)
    # Rewrite absolute paths to relative-looking ones for readability:
    #   /run/.../bob/.original/app/x.py  →  a/app/x.py
    #   /run/.../bob/working-copy/app/x.py  →  b/app/x.py
    # `git diff --no-index --no-prefix` strips the leading `/` from absolute
    # paths in its output, so we match both the with- and without-/ forms.
    for full, label in ((orig_str, "a"), (work_str, "b")):
        cleaned = cleaned.replace(full + "/", label + "/")
        cleaned = cleaned.replace(full.lstrip("/") + "/", label + "/")

    if len(cleaned.encode("utf-8")) > MAX_DIFF_BYTES:
        # Truncate at a line boundary near the limit
        truncated = cleaned.encode("utf-8")[:MAX_DIFF_BYTES].decode("utf-8", errors="ignore")
        truncated = truncated[: truncated.rfind("\n") + 1] if "\n" in truncated else truncated
        cleaned = truncated + f"\n... [truncated, full diff exceeded {MAX_DIFF_BYTES // 1024} KB]\n"
    return cleaned


def _diff_lines(working_copy: Path, original: Path) -> tuple[int, list[str]]:
    """git diff --no-index between original and working_copy, then filter
    out vendored dirs in Python (since --no-index does not accept pathspecs)."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--no-index", "--numstat", str(original), str(working_copy)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0, []

    total = 0
    files: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        if added == "-" or removed == "-":
            continue
        try:
            added_n = int(added)
            removed_n = int(removed)
        except ValueError:
            continue
        # git diff --no-index emits paths like
        #   "{<original>/X => <working_copy>/X}/sub/file.py"
        # or "/<original>/X/sub/file.py" and "/<working_copy>/X/sub/file.py".
        # Either way the path string CONTAINS the working_copy/original prefix,
        # so checking for any excluded dir as a substring is enough.
        if any(f"/{d}/" in path or path.endswith(f"/{d}") for d in EXCLUDED_DIRS):
            continue
        total += added_n + removed_n
        # Trim to a relative-ish form for display
        try:
            files.append(str(Path(path.split(" => ")[-1].rstrip("}")).name))
        except Exception:
            files.append(path)
    return total, files


def _run_semgrep(working_copy: Path, config: str) -> tuple[int, dict[str, int]]:
    semgrep = str(HARNESS_SEMGREP) if HARNESS_SEMGREP.exists() else "semgrep"
    excludes = []
    for d in EXCLUDED_DIRS:
        excludes.extend(["--exclude", d])
    try:
        proc = subprocess.run(
            [semgrep, "--config", config, "--json", "--quiet", *excludes, str(working_copy)],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0, {}

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return 0, {}

    results = data.get("results", [])
    by_sev: dict[str, int] = {}
    for r in results:
        sev = (r.get("extra") or {}).get("severity", "INFO")
        by_sev[sev] = by_sev.get(sev, 0) + 1
    return len(results), by_sev


def _any_forbidden_present(working_copy: Path, patterns: list[str]) -> bool:
    app_dir = working_copy / "app"
    if not app_dir.exists():
        return False
    for path in app_dir.rglob("*.py"):
        if _is_excluded(path.relative_to(working_copy)):
            continue
        text = path.read_text(errors="ignore")
        for pat in patterns:
            if re.search(pat, text):
                return True
    return False


def _run_verify_sh(working_copy: Path, verify_sh: Path) -> int:
    # Pass the harness's python so scenario verify.sh scripts don't have
    # to discover an interpreter or install pytest themselves.
    env = os.environ.copy()
    if HARNESS_PYTHON.exists():
        env["BAKEOFF_PYTHON"] = str(HARNESS_PYTHON)
    try:
        proc = subprocess.run(
            ["bash", str(verify_sh)],
            cwd=working_copy,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return proc.returncode
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1
