"""E2e test: task classification routes to correct profile in system prompt ON THE WIRE."""
from __future__ import annotations

import sys

import pytest

from tests.e2e_harness import bouzecode

# Same guard as the sibling mock_api suites (providers/test_mock_api_e2e.py,
# providers/test_resilience_mock_api_e2e.py, xml_protocol/test_xml_stream_e2e.py):
# threaded werkzeug + httpx streaming dead-locks on Windows (reader thread hangs on
# a socket that never EOFs), which wedges the whole worker and makes any full-suite
# run unreadable. Runs on Linux CI.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="mock_api e2e hangs on Windows (threaded werkzeug + httpx streaming)",
)


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

    def test_classification_is_off_by_default(self, monkeypatch):
        """Without an explicit opt-in, classification must not run. The classifier
        (if invoked) would label this crash report 'bug', so its TDD Bug-First
        profile would land on the wire — assert it is ABSENT, proving no
        classification (and no max_tokens=12 side-call) fired. Regression guard
        for the off-by-default switch; observed purely on the real wire payload."""
        monkeypatch.setattr(
            "bouzecode.backend.agent.loop.classify",
            lambda *args, **kwargs: {"type": "bug", "scope": "doute"},
        )

        result = bouzecode(
            messages=["The app crashes when I click save"],
            mock_api=["I'll look into it."],
            config_overrides={"enforce_methodology": False},  # NB: no task_classification opt-in
        )

        assert result.recorded_requests, "mock API should have recorded at least one request"
        system_text = _extract_system_text(result.recorded_requests[0])
        assert "TDD Bug-First" not in system_text

    # NB: the standalone bug.yaml / feature.yaml profiles (which carried the
    # "TDD Bug-First" / "TDD Feature-First" markers) were consolidated into
    # default.yaml — the default profile now contains BOTH the bug and the
    # feature TDD flows. Classification no longer swaps in a per-type profile, so
    # the old "injects X marker" assertions are gone. The off-by-default guard and
    # the "no bug/feature-specific marker leaks" guards below still hold.

    def test_default_classification_does_not_inject_bug_or_feature_profile(self, monkeypatch):
        """When classify_task returns 'default', neither bug nor feature profile appears."""
        monkeypatch.setattr(
            "bouzecode.backend.agent.loop.classify",
            lambda *args, **kwargs: {"type": "default", "scope": "doute"},
        )

        result = bouzecode(
            messages=["Tell me about the project structure"],
            mock_api=["Here's the structure."],
            config_overrides={"task_classification": True, "enforce_methodology": False},
        )

        assert result.recorded_requests, "mock API should have recorded at least one request"
        system_text = _extract_system_text(result.recorded_requests[0])
        assert "TDD Bug-First" not in system_text
        assert "TDD Feature-First" not in system_text


class TestProfileExtraContent:
    """Verify the default profile (which absorbed the bug+feature TDD flows) carries
    the substantive TDD guidance regardless of classification."""

    def test_feature_profile_has_substantial_content(self, monkeypatch):
        """Feature profile system_prompt_extra includes red-green-refactor instructions."""
        monkeypatch.setattr(
            "bouzecode.backend.agent.loop.classify",
            lambda *args, **kwargs: {"type": "feature", "scope": "doute"},
        )

        result = bouzecode(
            messages=["Add export button"],
            mock_api=["On it."],
            config_overrides={"task_classification": True, "enforce_methodology": False},
        )

        system_text = _extract_system_text(result.recorded_requests[0])
        # Feature profile must include the red-green-refactor cycle
        assert "red" in system_text.lower() or "Vérifie qu'il échoue" in system_text
