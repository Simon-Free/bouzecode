"""Unit tests for task_classifier.classify_task."""
from __future__ import annotations

import pytest
import bouzecode.backend.agent.task_classifier as tc_module


class FakeTextEvent:
    """Minimal event with .text attribute to simulate stream output."""
    def __init__(self, text: str):
        self.text = text


def _make_stream(response_text: str):
    """Return a callable that yields a single text event (matching dispatch.stream signature)."""
    def fake_stream(*, model, system, messages, tool_schemas, config):
        yield FakeTextEvent(response_text)
    return fake_stream


def _make_raising_stream(exc):
    """Return a callable that raises on iteration."""
    def fake_stream(*, model, system, messages, tool_schemas, config):
        raise exc
        yield  # noqa: unreachable — makes it a generator
    return fake_stream


@pytest.fixture(autouse=True)
def _patch_dispatch_stream(monkeypatch):
    """Reset the module-level dispatch_stream after each test."""
    original = tc_module.dispatch_stream
    yield
    tc_module.dispatch_stream = original


@pytest.fixture
def base_config():
    return {"model": "test-model", "task_classification": True, "_depth": 0}


class TestClassifyTask:
    """Tests for classify_task function."""

    def test_returns_feature(self, base_config):
        tc_module.dispatch_stream = _make_stream("feature")
        result = tc_module.classify_task("Add a new button to the UI", base_config)
        assert result == "feature"

    def test_returns_bug_case_insensitive(self, base_config):
        tc_module.dispatch_stream = _make_stream("Bug.")
        result = tc_module.classify_task("The app crashes on startup", base_config)
        assert result == "bug"

    def test_returns_feature_with_extra_text(self, base_config):
        tc_module.dispatch_stream = _make_stream("I think this is a Feature request")
        result = tc_module.classify_task("Implement dark mode", base_config)
        assert result == "feature"

    def test_garbage_returns_autre(self, base_config):
        tc_module.dispatch_stream = _make_stream("I don't understand the question xyz")
        result = tc_module.classify_task("hello world", base_config)
        assert result == "autre"

    def test_exception_returns_autre(self, base_config):
        tc_module.dispatch_stream = _make_raising_stream(ConnectionError("network down"))
        result = tc_module.classify_task("Fix the login bug", base_config)
        assert result == "autre"

    def test_disabled_by_config(self, base_config):
        base_config["task_classification"] = False
        # Should not call stream at all
        result = tc_module.classify_task("Add feature X", base_config)
        assert result == "autre"

    def test_disabled_at_depth_gt_0(self, base_config):
        base_config["_depth"] = 1
        result = tc_module.classify_task("Fix bug Y", base_config)
        assert result == "autre"

    def test_no_model_returns_autre(self):
        config = {"task_classification": True, "_depth": 0}
        result = tc_module.classify_task("Something", config)
        assert result == "autre"

    def test_truncates_long_message(self, base_config):
        long_msg = "x" * 5000
        captured_messages = []

        def capturing_stream(*, model, system, messages, tool_schemas, config):
            captured_messages.extend(messages)
            yield FakeTextEvent("feature")

        tc_module.dispatch_stream = capturing_stream
        tc_module.classify_task(long_msg, base_config)
        assert len(captured_messages[0]["content"]) == 2000


class TestClassifyScope:
    """Scope axis (borné/exploratoire/doute) of the combined classify() call."""

    def test_two_word_reply_parses_both_axes(self, base_config):
        tc_module.dispatch_stream = _make_stream("bug exploratoire")
        result = tc_module.classify("Fix the flaky session save", base_config)
        assert result == {"type": "bug", "scope": "exploratoire"}

    def test_borne_accent_insensitive(self, base_config):
        tc_module.dispatch_stream = _make_stream("feature borne")
        assert tc_module.classify("Crée le fichier X avec Y", base_config)["scope"] == "borné"

    def test_garbage_scope_is_doute(self, base_config):
        tc_module.dispatch_stream = _make_stream("feature")
        assert tc_module.classify("Add X", base_config)["scope"] == "doute"

    def test_exception_returns_fallback(self, base_config):
        tc_module.dispatch_stream = _make_raising_stream(ConnectionError("down"))
        assert tc_module.classify("Fix Y", base_config) == {"type": "autre", "scope": "doute"}

    def test_depth_gate_returns_fallback(self, base_config):
        base_config["_depth"] = 1
        assert tc_module.classify("Fix Y", base_config) == {"type": "autre", "scope": "doute"}
