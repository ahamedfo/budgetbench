#!/usr/bin/env bash
# Binary pass/fail for the 01-sqli-flask scenario.
#
# Universal contract (every scenario's verify.sh follows this):
#   • Operates on the CODE-UNDER-TEST directory (repo contents — app/,
#     tests/, requirements.txt all at the top level).
#   • The harness runs it with cwd = the working-copy. So no cd needed.
#   • For standalone testing from the scenario root, this script auto-
#     detects and cd's into repo/.
#   • Honors $BAKEOFF_PYTHON if set (the harness passes its .venv's
#     python so the script doesn't have to discover one).
#
# Exits 0 ONLY when:
#   1. pytest passes (all tests, existing + any the tool added)
#   2. Semgrep p/python reports zero findings
#   3. No vulnerable f-string SQL pattern remains
# Otherwise exits non-zero.

set -u

# ── Locate the code-under-test ─────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$PWD" = "$SCRIPT_DIR" ] && [ -d "$SCRIPT_DIR/repo" ]; then
    # Standalone mode: user ran `bash verify.sh` from the scenario root.
    cd "$SCRIPT_DIR/repo"
fi
# Otherwise: harness mode — cwd is already the working-copy.

PY="${BAKEOFF_PYTHON:-python3}"
FAIL=0

echo "==> Installing requirements (silent)..."
"$PY" -m pip install -q -r requirements.txt 2>/dev/null || true

echo "==> Running pytest..."
if ! "$PY" -m pytest -q >/tmp/verify-pytest.log 2>&1; then
    echo "FAIL: pytest did not pass." >&2
    tail -30 /tmp/verify-pytest.log >&2
    FAIL=1
else
    echo "  pytest: pass"
fi

echo "==> Running Semgrep (p/python)..."
if command -v semgrep >/dev/null 2>&1; then
    SEMGREP_FINDINGS=$(semgrep --config=p/python --json --quiet . 2>/dev/null \
        | "$PY" -c 'import json,sys; print(len(json.load(sys.stdin).get("results",[])))' 2>/dev/null \
        || echo "?")
    if [ "$SEMGREP_FINDINGS" = "0" ]; then
        echo "  semgrep: 0 findings"
    else
        echo "FAIL: Semgrep p/python still reports $SEMGREP_FINDINGS finding(s)." >&2
        semgrep --config=p/python --quiet . >&2 || true
        FAIL=1
    fi
else
    echo "  semgrep: skipped (not installed in env)"
fi

echo "==> Grepping for vulnerable f-string SQL pattern..."
if grep -rEn 'f"[^"]*SELECT[^"]*\{' app/ >/dev/null 2>&1; then
    echo "FAIL: vulnerable f-string SQL pattern still present:" >&2
    grep -rEn 'f"[^"]*SELECT[^"]*\{' app/ >&2 || true
    FAIL=1
else
    echo "  vuln pattern: removed"
fi

if [ $FAIL -eq 0 ]; then
    echo "==> VERIFY: PASS"
    exit 0
else
    echo "==> VERIFY: FAIL"
    exit 1
fi
