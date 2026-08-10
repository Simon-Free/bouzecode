# [desc] Trivial always-passing test used as a target fixture by test_e2e_run_python_test. [/desc]
"""Trivial test that always passes — used as target by test_e2e_run_python_test."""


def test_always_passes():
    assert 1 + 1 == 2
