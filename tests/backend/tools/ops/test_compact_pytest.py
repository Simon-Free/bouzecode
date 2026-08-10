"""Tests for compact_pytest_output in truncation module."""

from bouzecode.backend.tools.ops.truncation import compact_pytest_output


# --- Fixtures: sample pytest outputs ---

ALL_GREEN_OUTPUT = """\
============================= test session starts ==============================
platform win32 -- Python 3.12.0, pytest-8.0.0, pluggy-1.4.0
rootdir: C:\\project
collected 5 items

tests/test_a.py .....                                                    [100%]

============================== 5 passed in 1.23s ===============================
"""

ALL_GREEN_VERBOSE_OUTPUT = """\
============================= test session starts ==============================
platform win32 -- Python 3.12.0, pytest-8.0.0, pluggy-1.4.0
rootdir: C:\\project
collected 3 items

tests/test_a.py::test_one PASSED                                         [ 33%]
tests/test_a.py::test_two PASSED                                         [ 66%]
tests/test_a.py::test_three PASSED                                       [100%]

============================== 3 passed in 0.45s ===============================
"""

FAILURE_OUTPUT = """\
============================= test session starts ==============================
platform win32 -- Python 3.12.0, pytest-8.0.0, pluggy-1.4.0
rootdir: C:\\project
collected 5 items

tests/test_a.py ...F.                                                    [100%]

=================================== FAILURES ===================================
_________________________________ test_broken __________________________________

    def test_broken():
        x = 1
>       assert x == 2
E       AssertionError: assert 1 == 2

tests/test_a.py:10: AssertionError
=========================== short test summary info ============================
FAILED tests/test_a.py::test_broken - AssertionError: assert 1 == 2
============================== 1 failed, 4 passed in 1.50s =====================
"""

TWO_FAILURES_OUTPUT = """\
============================= test session starts ==============================
platform win32 -- Python 3.12.0, pytest-8.0.0, pluggy-1.4.0
rootdir: C:\\project
collected 10 items

tests/test_a.py ...F..                                                   [ 60%]
tests/test_b.py ..F.                                                     [100%]

=================================== FAILURES ===================================
_________________________________ test_broken __________________________________

    def test_broken():
        x = 1
>       assert x == 2
E       AssertionError: assert 1 == 2

tests/test_a.py:10: AssertionError
_________________________________ test_other ___________________________________

    def test_other():
        data = {"key": "value"}
>       assert data["key"] == "wrong"
E       AssertionError: assert 'value' == 'wrong'

tests/test_b.py:5: AssertionError
=========================== short test summary info ============================
FAILED tests/test_a.py::test_broken - AssertionError: assert 1 == 2
FAILED tests/test_b.py::test_other - AssertionError: assert 'value' == 'wrong'
============================== 2 failed, 8 passed in 2.10s =====================
"""

ERROR_OUTPUT = """\
============================= test session starts ==============================
platform win32 -- Python 3.12.0, pytest-8.0.0, pluggy-1.4.0
rootdir: C:\\project
collected 3 items

=============================== ERRORS ========================================
_________________ ERROR collecting tests/test_bad.py __________________________

ModuleNotFoundError: No module named 'missing_dep'

============================== 1 error in 0.30s ================================
"""

WARNING_OUTPUT = """\
============================= test session starts ==============================
platform win32 -- Python 3.12.0, pytest-8.0.0, pluggy-1.4.0
rootdir: C:\\project
collected 5 items

tests/test_a.py .....                                                    [100%]

=============================== warnings summary ===============================
tests/test_a.py::test_one
  DeprecationWarning: use new_func instead
    old_func()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
============================== 5 passed, 1 warning in 1.00s ====================
"""

NON_PYTEST_OUTPUT = """\
Hello world
This is just normal command output
Nothing to do with pytest
Line 4
Line 5
"""


class TestCompactPytestAllGreen:
    """When all tests pass, output should be compact."""

    def test_keeps_summary_line(self):
        result = compact_pytest_output(ALL_GREEN_OUTPUT)
        assert "5 passed" in result

    def test_removes_header_noise(self):
        result = compact_pytest_output(ALL_GREEN_OUTPUT)
        assert "test session starts" not in result
        assert "platform win32" not in result

    def test_removes_progress_dots(self):
        result = compact_pytest_output(ALL_GREEN_OUTPUT)
        assert "....." not in result

    def test_lists_tests_when_verbose_and_few(self):
        result = compact_pytest_output(ALL_GREEN_VERBOSE_OUTPUT)
        assert "3 passed" in result
        # Should list test names when verbose and <20 tests
        assert "test_one" in result
        assert "test_two" in result
        assert "test_three" in result

    def test_keeps_warnings_on_green(self):
        result = compact_pytest_output(WARNING_OUTPUT)
        assert "DeprecationWarning" in result
        assert "5 passed" in result


class TestCompactPytestFailures:
    """When tests fail, tracebacks must be preserved integrally."""

    def test_preserves_full_traceback(self):
        result = compact_pytest_output(FAILURE_OUTPUT)
        assert "def test_broken():" in result
        assert "assert x == 2" in result
        assert "AssertionError" in result

    def test_preserves_summary_line(self):
        result = compact_pytest_output(FAILURE_OUTPUT)
        assert "1 failed, 4 passed" in result

    def test_removes_header_noise(self):
        result = compact_pytest_output(FAILURE_OUTPUT)
        assert "test session starts" not in result
        assert "platform win32" not in result

    def test_removes_progress_dots(self):
        result = compact_pytest_output(FAILURE_OUTPUT)
        # The dots line "tests/test_a.py ...F." should be removed
        assert "...F." not in result

    def test_two_failures_both_preserved(self):
        result = compact_pytest_output(TWO_FAILURES_OUTPUT)
        assert "test_broken" in result
        assert "test_other" in result
        assert "assert x == 2" in result
        assert "assert 'value' == 'wrong'" in result
        assert "2 failed, 8 passed" in result


class TestCompactPytestErrors:
    """Collection errors must be preserved."""

    def test_preserves_error_block(self):
        result = compact_pytest_output(ERROR_OUTPUT)
        assert "ModuleNotFoundError" in result
        assert "missing_dep" in result

    def test_preserves_summary(self):
        result = compact_pytest_output(ERROR_OUTPUT)
        assert "1 error" in result


class TestCompactNonPytest:
    """Non-pytest output must pass through unchanged."""

    def test_non_pytest_unchanged(self):
        result = compact_pytest_output(NON_PYTEST_OUTPUT)
        assert result == NON_PYTEST_OUTPUT
