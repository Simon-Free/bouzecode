# [desc] Unit tests for close_validator.validate_close (verdict parsing, gates, best-effort acceptance). [/desc]
from __future__ import annotations

import pytest
import bouzecode.backend.agent.close_validator as cv


class FakeTextEvent:
    def __init__(self, text: str):
        self.text = text


def _make_stream(response_text: str, calls: list | None = None):
    def fake_stream(*, model, system, messages, tool_schemas, config):
        if calls is not None:
            calls.append({"model": model, "config": config, "messages": messages})
        yield FakeTextEvent(response_text)
    return fake_stream


@pytest.fixture(autouse=True)
def _reset_stream():
    original = cv.dispatch_stream
    yield
    cv.dispatch_stream = original


@pytest.fixture
def native_config():
    # deepseek-* uses native tool-calling -> the validator gate is open
    return {"model": "deepseek-v4-flash", "close_validation": True, "_depth": 0}


def test_ok_verdict_accepts(native_config):
    cv.dispatch_stream = _make_stream("OK")
    assert cv.validate_close("tout est fait", native_config) == (True, "")


def test_ko_verdict_refuses_with_feedback(native_config):
    cv.dispatch_stream = _make_stream("KO: les tests n'ont pas été lancés")
    accepted, feedback = cv.validate_close("fini", native_config)
    assert accepted is False
    assert "tests" in feedback


def test_exception_accepts_best_effort(native_config):
    def raising(**_kw):
        raise ConnectionError("down")
        yield  # noqa: make generator
    cv.dispatch_stream = raising
    assert cv.validate_close("fini", native_config) == (True, "")


def test_disabled_by_config_skips_call(native_config):
    native_config["close_validation"] = False
    calls: list = []
    cv.dispatch_stream = _make_stream("KO: jamais lu", calls)
    assert cv.validate_close("fini", native_config) == (True, "")
    assert calls == []


def test_validator_call_is_light(native_config):
    calls: list = []
    cv.dispatch_stream = _make_stream("OK", calls)
    cv.validate_close("fini", native_config)
    side_config = calls[0]["config"]
    assert side_config["thinking_mode"] == "off"
    assert side_config["max_tokens"] == cv._MAX_TOKENS
    assert side_config["_depth"] == 1
