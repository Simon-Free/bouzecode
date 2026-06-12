# [desc] Unit tests for auth error retry logic — model access denied vs transient 401 handling
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Unit tests for auth error retry logic — model access denied vs transient 401 handling</param></tool_use> [/desc]
"""Unit tests for _create_anthropic_stream_with_retry auth error handling."""
import pytest

from bouzecode.backend.agent.providers.backends.anthropic_helpers import _create_anthropic_stream_with_retry


class FakeResponse:
    status_code = 401
    headers = {}

    def json(self):
        return {"error": {"message": "key not allowed to access model", "type": "key_model_access_denied"}}


class FakeAuthError(Exception):
    """Mimics anthropic.AuthenticationError."""
    def __init__(self, message):
        self.message = message
        self.status_code = 401
        self.response = FakeResponse()
        super().__init__(message)

    def __str__(self):
        return self.message


def _patch_anthropic_error(monkeypatch):
    """Make anthropic module's AuthenticationError point to our fake."""
    import anthropic as _ant
    monkeypatch.setattr(_ant, "AuthenticationError", FakeAuthError)


def test_model_access_denied_raises_immediately(monkeypatch):
    """Model access denied (permanent) should raise immediately, no retry."""
    _patch_anthropic_error(monkeypatch)

    call_count = 0

    class FakeClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                nonlocal call_count
                call_count += 1
                raise FakeAuthError(
                    "key not allowed to access model. "
                    "This key can only access models=['gold', 'premium']. "
                    "Tried to access claude-sonnet-4-20250514"
                )

    warnings = []
    with pytest.raises(FakeAuthError, match="not allowed to access model"):
        _create_anthropic_stream_with_retry(
            FakeClient(),
            {"model": "claude-sonnet-4-20250514", "messages": []},
            warn=warnings.append,
            sleep=lambda _: None,
        )

    # Should NOT retry — only 1 call
    assert call_count == 1, f"Expected 1 call (no retry), got {call_count}"
    # Should have printed the red error
    assert any("Model access denied" in w for w in warnings)


def test_generic_auth_error_retries_then_raises(monkeypatch):
    """Generic 401 (not model access) should retry 3 times then raise."""
    _patch_anthropic_error(monkeypatch)

    call_count = 0

    class FakeClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                nonlocal call_count
                call_count += 1
                raise FakeAuthError("transient proxy auth failure")

    warnings = []
    with pytest.raises(FakeAuthError, match="transient proxy auth failure"):
        _create_anthropic_stream_with_retry(
            FakeClient(),
            {"model": "claude-sonnet-4-20250514", "messages": []},
            warn=warnings.append,
            sleep=lambda _: None,
        )

    # Should retry 3 times total
    assert call_count == 3, f"Expected 3 attempts, got {call_count}"
