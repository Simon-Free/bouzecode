# [desc] <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests retry logic for OpenRouter HTTP requests with backoff, budget exhaustion, and error handling</param></tool_use> [/desc]
import pytest

from bouzecode.backend.agent.providers.backends.openrouter_retry import (
    post_with_retry, BACKOFFS_S,
)


class FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = text


def _runner(statuses):
    """post_once stub yielding FakeResponses in order; records sleep delays."""
    responses = [FakeResponse(s) for s in statuses]
    delays = []
    resp = post_with_retry(lambda: responses.pop(0), sleep=delays.append)
    return resp, delays


def test_ok_first_try_no_sleep():
    resp, delays = _runner([200])
    assert resp.ok and delays == []


def test_429_then_ok_backs_off_once():
    resp, delays = _runner([429, 200])
    assert resp.ok and delays == [BACKOFFS_S[0]]


def test_5xx_sequence_exponential_backoff():
    resp, delays = _runner([500, 503, 200])
    assert resp.ok and delays == list(BACKOFFS_S[:2])


def test_429_budget_exhausted_raises_with_body():
    responses = [FakeResponse(429, "rate-limited upstream")] * (len(BACKOFFS_S) + 1)
    with pytest.raises(RuntimeError, match="HTTP 429"):
        post_with_retry(lambda: responses.pop(0), sleep=lambda _s: None)


def test_400_retried_once_then_ok():
    # Observed live: a 400 from one bad fallback provider right after a 429;
    # one rotation retry lands on a healthy provider.
    resp, delays = _runner([400, 200])
    assert resp.ok and len(delays) == 1


def test_400_twice_raises_with_body():
    responses = [FakeResponse(400, "invalid request params")] * 2
    with pytest.raises(RuntimeError, match="invalid request params"):
        post_with_retry(lambda: responses.pop(0), sleep=lambda _s: None)


def test_other_4xx_raises_immediately():
    with pytest.raises(RuntimeError, match="HTTP 401"):
        post_with_retry(lambda: FakeResponse(401, "bad key"), sleep=lambda _s: None)


def test_mixed_429_then_400_then_ok():
    resp, delays = _runner([429, 400, 200])
    assert resp.ok and len(delays) == 2
