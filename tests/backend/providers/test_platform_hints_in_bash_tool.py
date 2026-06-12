"""Verify platform hints are located in the Bash tool description (not system prompt)."""
import platform

import pytest

from bouzecode.backend.tools.schemas import TOOL_SCHEMAS


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only hints")
class TestPlatformHintsInBashTool:
    """Platform hints should be in Bash tool description, not system prompt."""

    def test_system_prompt_does_not_contain_platform_hints(self):
        """The system prompt should NOT contain Windows shell hints."""
        from bouzecode.backend.core.context import build_system_prompt_parts

        stable, volatile = build_system_prompt_parts({})
        full_prompt = stable + volatile
        assert "Do NOT use Unix commands" not in full_prompt, (
            "Platform hints should not be in the system prompt"
        )

    def test_bash_tool_description_contains_platform_hints(self):
        """The Bash tool schema description should contain Windows shell hints."""
        bash_schema = next(s for s in TOOL_SCHEMAS if s["name"] == "Bash")
        desc = bash_schema["description"]
        # The hints mention specific command replacements
        assert "type file.txt" in desc, (
            f"Bash tool description should contain platform hints, got: {desc[:200]}"
        )
        assert "WINDOWS SHELL RULES" in desc or "Do NOT use Unix commands" in desc
