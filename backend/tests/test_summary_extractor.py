from src.scoring.summary_extractor import extract_sections, section_completeness


GOOD_OUTPUT = """
I reviewed the code and found an issue.

## VULNERABILITIES FOUND
- SQL injection in app/routes/products.py:38 (search_products)
  Uses f-string interpolation into raw SQL via text().

## FIXES APPLIED
Changed the search_products endpoint to use parameterized queries.
This binds `q` as a parameter instead of interpolating it.

## TESTS ADDED
- test_search_products_sqli_safe verifies that a malicious payload
  is treated as literal text, not SQL.

## TEST RESULTS
26 passed in 2.9s
"""

MISSING_TWO = """
## VULNERABILITIES FOUND
SQLi in products.py

## FIXES APPLIED
Used parameterized queries.

(The model forgot the other two sections.)
"""

ALL_MISSING = "I fixed the bug. All tests pass."


def test_all_four_sections_extracted():
    s = extract_sections(GOOD_OUTPUT)
    assert all(s.raw_section_found.values())
    assert "SQL injection" in s.vulnerabilities_found
    assert "parameterized" in s.fixes_applied.lower()
    assert "test_search_products_sqli_safe" in s.tests_added
    assert "26 passed" in s.test_results
    assert section_completeness(s) == 1.0


def test_partial_sections_extracted():
    s = extract_sections(MISSING_TWO)
    assert s.raw_section_found["vulnerabilities_found"] is True
    assert s.raw_section_found["fixes_applied"] is True
    assert s.raw_section_found["tests_added"] is False
    assert s.raw_section_found["test_results"] is False
    assert section_completeness(s) == 0.5


def test_no_sections_found():
    s = extract_sections(ALL_MISSING)
    assert not any(s.raw_section_found.values())
    assert section_completeness(s) == 0.0


def test_empty_string():
    s = extract_sections("")
    assert section_completeness(s) == 0.0


def test_case_insensitive_headers():
    out = """
## vulnerabilities found
Found SQLi.

## Fixes Applied
Fixed it.

## tests added
- new_test

## TEST RESULTS
all green
"""
    s = extract_sections(out)
    assert section_completeness(s) == 1.0


def test_generic_headers_work_for_feature_scenarios():
    """Feature/refactor/bugfix scenarios use generic header names; the
    extractor must accept them into the same internal fields."""
    out = """
## TASK SUMMARY
The export endpoint was missing — added it.

## CODE CHANGES
Added GET /users/export to app/routes/users.py.

## TESTS ADDED
- test_export_returns_csv

## TEST RESULTS
12 passed
"""
    s = extract_sections(out)
    assert s.raw_section_found["vulnerabilities_found"] is True   # mapped from TASK SUMMARY
    assert s.raw_section_found["fixes_applied"] is True            # mapped from CODE CHANGES
    assert "missing" in s.vulnerabilities_found
    assert "Added GET" in s.fixes_applied


def test_h3_headers_also_work():
    out = """
### VULNERABILITIES FOUND
Something.

### FIXES APPLIED
Did this.

### TESTS ADDED
Added X.

### TEST RESULTS
ok
"""
    s = extract_sections(out)
    assert section_completeness(s) == 1.0
