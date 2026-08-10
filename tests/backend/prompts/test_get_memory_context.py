"""Test that get_memory_context is defined and build_system_prompt_parts works."""


def test_build_system_prompt_no_nameerror():
    """Reproduces the NameError bug: build_system_prompt_parts must not crash."""
    from bouzecode.backend.core.context import build_system_prompt_parts

    stable, volatile = build_system_prompt_parts({})
    assert isinstance(stable, str)
    assert isinstance(volatile, str)


def test_get_memory_context_returns_string():
    """get_memory_context must exist and return a string."""
    from bouzecode.backend.core.context import get_memory_context

    result = get_memory_context()
    assert isinstance(result, str)
