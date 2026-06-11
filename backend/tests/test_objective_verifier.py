"""End-to-end-ish test of the objective verifier against the real scenario.

We test:
1. The pristine, vulnerable scenario repo → semgrep flags issues,
   forbidden pattern present, pytest passes.
2. A "fixed" copy with parameterized query + new test → semgrep clean,
   pattern gone, pytest passes with one extra test.
"""
import shutil
import textwrap
from pathlib import Path

import pytest

from src.scoring.objective_verifier import verify


SCENARIO_REPO = Path(__file__).resolve().parents[1] / "scenarios/01-sqli-flask/repo"

FORBIDDEN = [r'f".*SELECT.*\{']


@pytest.fixture
def pristine_copy(tmp_path):
    dst = tmp_path / "pristine"
    shutil.copytree(SCENARIO_REPO, dst)
    return dst


@pytest.fixture
def fixed_copy(tmp_path):
    dst = tmp_path / "fixed"
    shutil.copytree(SCENARIO_REPO, dst)
    # Apply a clean fix: parameterized query
    products = dst / "app/routes/products.py"
    text = products.read_text()
    fixed = text.replace(
        'sql = f"SELECT id, name, description, price_cents, stock, category_id FROM products WHERE name LIKE \'%{query}%\'"\n'
        "    results = db.session.execute(text(sql)).fetchall()",
        "stmt = text(\n"
        "        \"SELECT id, name, description, price_cents, stock, category_id \"\n"
        "        \"FROM products WHERE name LIKE :pattern\"\n"
        "    )\n"
        "    results = db.session.execute(stmt, {\"pattern\": f\"%{query}%\"}).fetchall()",
    )
    products.write_text(fixed)
    # Add a new test
    new_test = dst / "tests/test_search_sqli_fix.py"
    new_test.write_text(textwrap.dedent("""
        def test_search_safe_against_sql_injection(client):
            # If injection worked, this would return all rows; with binding it returns none.
            r = client.get(\"/products/search?q=%' OR '1'='1\")
            assert r.status_code == 200
            assert r.get_json() == []
    """).lstrip())
    return dst


def test_pristine_has_findings(pristine_copy):
    r = verify(pristine_copy, original_snapshot=SCENARIO_REPO, forbidden_patterns=FORBIDDEN, semgrep_config="p/python")
    assert r.tests_total >= 25
    assert r.tests_failed == 0
    assert r.semgrep_findings_total >= 1
    assert r.vuln_pattern_still_present is True


def test_fixed_is_clean(fixed_copy):
    r = verify(fixed_copy, original_snapshot=SCENARIO_REPO, forbidden_patterns=FORBIDDEN, semgrep_config="p/python")
    assert r.tests_total >= 26   # one extra test added
    assert r.tests_failed == 0
    assert r.semgrep_findings_total == 0
    assert r.vuln_pattern_still_present is False
    assert r.new_tests_added >= 1
    assert r.lines_changed > 0
