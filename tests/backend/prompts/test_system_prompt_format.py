# [desc] Tests that system prompt template renders without KeyError on curly braces [/desc]
"""Test that the system prompt template renders without KeyError."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_build_system_prompt_no_keyerror():
    """build_system_prompt should not raise KeyError on curly braces in template text."""
    from bouzecode.backend.core.context import build_system_prompt

    prompt = build_system_prompt({})
    assert "Bouzecode" in prompt
    assert "{platform}" not in prompt
    assert "{platform_hints}" not in prompt
    assert "{claude_md}" not in prompt
