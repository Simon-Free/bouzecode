# [desc] Trivial always-passing test used as a target for RunPythonTest e2e validation [/desc]
"""Trivial test that always passes — used as target by test_e2e_run_python_test."""


def test_always_passes():
    assert 1 + 1 == 2
