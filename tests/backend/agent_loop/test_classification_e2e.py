"""E2e test: task classification routes to correct profile in system prompt ON THE WIRE."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="Depends on profile YAML content (TDD Bug-First/Feature-First) not ported to OSS")

from tests.e2e_harness import bouzecode


METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


def _extract_system_text(recorded_request: dict) -> str:
    """Extract the full system prompt text from a recorded wire request body."""
    system = recorded_request.get("system", "")
    if isinstance(system, str):
        return system
    # List of content blocks (Anthropic format with cache_control)
    parts = []
    for block in system:
        if isinstance(block, dict):
            parts.append(block.get("text", ""))
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(parts)


class TestClassificationProfileOnWire:
    """Verify that classification injects the correct profile into the REAL wire payload."""

    def test_bug_classification_injects_bug_profile_in_system_prompt(self, monkeypatch):
        """When classify_task returns 'bug', the wire system prompt contains TDD Bug-First."""
        monkeypatch.setattr(
            "bouzecode.backend.agent.loop.classify",
            lambda *args, **kwargs: {"type": "bug", "scope": "doute"},
        )

        result = bouzecode(
            messages=["The app crashes when I click save"],
            mock_api=[f"I'll fix the bug.\n{METH}"],
            config_overrides={"task_classification": True, "enforce_methodology": False},
        )

        assert result.recorded_requests, "mock API should have recorded at least one request"
        system_text = _extract_system_text(result.recorded_requests[0])
        assert "TDD Bug-First" in system_text, (
            f"Bug profile marker 'TDD Bug-First' not found in system prompt:\n{system_text[:500]}"
        )

    def test_feature_classification_injects_feature_profile_in_system_prompt(self, monkeypatch):
        """When classify_task returns 'feature', the wire system prompt contains TDD Feature-First."""
        monkeypatch.setattr(
            "bouzecode.backend.agent.loop.classify",
            lambda *args, **kwargs: {"type": "feature", "scope": "doute"},
        )

        result = bouzecode(
            messages=["Add a dark mode toggle to the settings page"],
            mock_api=[f"I'll add the feature.\n{METH}"],
            config_overrides={"task_classification": True, "enforce_methodology": False},
        )

        assert result.recorded_requests, "mock API should have recorded at least one request"
        system_text = _extract_system_text(result.recorded_requests[0])
        assert "TDD Feature-First" in system_text, (
            f"Feature profile marker 'TDD Feature-First' not found in system prompt:\n{system_text[:500]}"
        )

    def test_default_classification_does_not_inject_bug_or_feature_profile(self, monkeypatch):
        """When classify_task returns 'default', neither bug nor feature profile appears."""
        monkeypatch.setattr(
            "bouzecode.backend.agent.loop.classify",
            lambda *args, **kwargs: {"type": "default", "scope": "doute"},
        )

        result = bouzecode(
            messages=["Tell me about the project structure"],
            mock_api=[f"Here's the structure.\n{METH}"],
            config_overrides={"task_classification": True, "enforce_methodology": False},
        )

        assert result.recorded_requests, "mock API should have recorded at least one request"
        system_text = _extract_system_text(result.recorded_requests[0])
        assert "TDD Bug-First" not in system_text
        assert "TDD Feature-First" not in system_text


class TestProfileExtraContent:
    """Verify profiles contain expected content (not empty placeholders)."""

    def test_bug_profile_has_substantial_content(self, monkeypatch):
        """Bug profile system_prompt_extra includes reproduction-first instructions."""
        monkeypatch.setattr(
            "bouzecode.backend.agent.loop.classify",
            lambda *args, **kwargs: {"type": "bug", "scope": "doute"},
        )

        result = bouzecode(
            messages=["Fix the crash"],
            mock_api=[f"On it.\n{METH}"],
            config_overrides={"task_classification": True, "enforce_methodology": False},
        )

        system_text = _extract_system_text(result.recorded_requests[0])
        # Bug profile must include the reproduction-first instruction
        assert "Reproduis d'abord le bug par un test" in system_text

    def test_feature_profile_has_substantial_content(self, monkeypatch):
        """Feature profile system_prompt_extra includes red-green-refactor instructions."""
        monkeypatch.setattr(
            "bouzecode.backend.agent.loop.classify",
            lambda *args, **kwargs: {"type": "feature", "scope": "doute"},
        )

        result = bouzecode(
            messages=["Add export button"],
            mock_api=[f"On it.\n{METH}"],
            config_overrides={"task_classification": True, "enforce_methodology": False},
        )

        system_text = _extract_system_text(result.recorded_requests[0])
        # Feature profile must include the red-green-refactor cycle
        assert "red" in system_text.lower() or "Vérifie qu'il échoue" in system_text
