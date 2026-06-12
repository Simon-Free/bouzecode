# [desc] Slow pytest target with sleep and @slow marker for timeout/filtering tests. [/desc]
"""Test target that sleeps — used for marker filtering and timeout tests."""

import time

import pytest


@pytest.mark.slow
def test_slow_operation():
    """Intentionally slow test for timeout testing."""
    time.sleep(30)
    assert True
