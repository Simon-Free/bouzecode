"""Tests for the session costs aggregation service."""
from __future__ import annotations

import pytest

from bouzecode.web_v2.services.sessions.costs import _cache_hit_pct, session_costs


# ---------- Unit tests for _cache_hit_pct ----------

def test_cache_hit_pct_zero_input():
    assert _cache_hit_pct(0, 0) == 0.0


def test_cache_hit_pct_normal():
    # 800 / (1000 + 800) = 44.4%
    assert _cache_hit_pct(1000, 800) == 44.4


def test_cache_hit_pct_partial():
    # 333 / (1000 + 333) = 25.0%
    assert _cache_hit_pct(1000, 333) == 25.0


def test_cache_hit_pct_cache_read_exceeds_input():
    """When cache_read > input_tokens, result is still <= 100%."""
    # 15000 / (5000 + 15000) = 75.0%
    assert _cache_hit_pct(5000, 15000) == 75.0


def test_cache_hit_pct_all_cached():
    # 10000 / (0 + 10000) = 100%
    assert _cache_hit_pct(0, 10000) == 100.0


# ---------- Integration tests with mock data ----------

@pytest.fixture()
def fake_session(tmp_path, monkeypatch):
    """Patch extract_per_call_data to return controlled data."""
    call_data = {
        "model": "claude-opus-4-6",
        "system_prompt_tokens": 5000,
        "calls": [
            {
                "turn": 1,
                "model": "claude-opus-4-6",
                "timestamp": 1000.0,
                "api_input_tokens": 10000,
                "api_output_tokens": 2000,
                "api_cache_read": 8000,
                "api_cache_create": 1000,
                "items": [],
            },
            {
                "turn": 2,
                "model": "claude-opus-4-6",
                "timestamp": 1010.0,
                "api_input_tokens": 12000,
                "api_output_tokens": 3000,
                "api_cache_read": 10000,
                "api_cache_create": 500,
                "items": [],
            },
        ],
    }
    monkeypatch.setattr(
        "bouzecode.web_v2.services.sessions.costs.extract_per_call_data",
        lambda path: call_data,
    )
    return tmp_path / "session.json"


@pytest.fixture()
def multi_model_session(tmp_path, monkeypatch):
    """Session with two different models."""
    call_data = {
        "model": "claude-opus-4-6",
        "system_prompt_tokens": 5000,
        "calls": [
            {
                "turn": 1,
                "model": "claude-opus-4-6",
                "timestamp": 1000.0,
                "api_input_tokens": 10000,
                "api_output_tokens": 2000,
                "api_cache_read": 8000,
                "api_cache_create": 1000,
                "items": [],
            },
            {
                "turn": 2,
                "model": "claude-sonnet-4-20250514",
                "timestamp": 1010.0,
                "api_input_tokens": 5000,
                "api_output_tokens": 1000,
                "api_cache_read": 3000,
                "api_cache_create": 500,
                "items": [],
            },
        ],
    }
    monkeypatch.setattr(
        "bouzecode.web_v2.services.sessions.costs.extract_per_call_data",
        lambda path: call_data,
    )
    return tmp_path / "session.json"


@pytest.fixture()
def empty_session(tmp_path, monkeypatch):
    """Session with no compaction_log → returns None."""
    monkeypatch.setattr(
        "bouzecode.web_v2.services.sessions.costs.extract_per_call_data",
        lambda path: None,
    )
    return tmp_path / "session.json"


def test_session_costs_single_model(fake_session):
    result = session_costs(str(fake_session))
    assert result is not None
    assert "claude-opus-4-6" in result["models"]
    m = result["models"]["claude-opus-4-6"]
    assert m["calls"] == 2
    assert m["input_tokens"] == 22000
    assert m["output_tokens"] == 5000
    assert m["cache_read_tokens"] == 18000
    assert m["cache_write_tokens"] == 1500
    assert m["cache_hit_pct"] == _cache_hit_pct(22000, 18000)
    assert m["cost"] > 0

    # Total matches the single model
    t = result["total"]
    assert t["calls"] == 2
    assert t["input_tokens"] == 22000
    assert t["cost"] == m["cost"]


def test_session_costs_multi_model(multi_model_session):
    result = session_costs(str(multi_model_session))
    assert result is not None
    assert len(result["models"]) == 2
    assert "claude-opus-4-6" in result["models"]
    assert "claude-sonnet-4-20250514" in result["models"]

    opus = result["models"]["claude-opus-4-6"]
    sonnet = result["models"]["claude-sonnet-4-20250514"]
    assert opus["calls"] == 1
    assert sonnet["calls"] == 1

    t = result["total"]
    assert t["calls"] == 2
    assert t["input_tokens"] == 15000
    assert t["output_tokens"] == 3000
    assert abs(t["cost"] - (opus["cost"] + sonnet["cost"])) < 0.0001


def test_session_costs_empty(empty_session):
    result = session_costs(str(empty_session))
    assert result is None


@pytest.fixture()
def empty_model_session(tmp_path, monkeypatch):
    """Session where per-call model is empty AND session model is empty."""
    call_data = {
        "model": "",
        "system_prompt_tokens": 3000,
        "calls": [
            {
                "turn": 1,
                "model": "",
                "timestamp": 1000.0,
                "api_input_tokens": 5000,
                "api_output_tokens": 1000,
                "api_cache_read": 15000,
                "api_cache_create": 200,
                "items": [],
            },
        ],
    }
    monkeypatch.setattr(
        "bouzecode.web_v2.services.sessions.costs.extract_per_call_data",
        lambda path: call_data,
    )
    return tmp_path / "session.json"


def test_session_costs_empty_model_unpriced(empty_model_session):
    """When model is unknown, cost=0 and unpriced flag is set."""
    result = session_costs(str(empty_model_session))
    assert result is not None
    assert result.get("unpriced") is True
    assert "note" in result
    # Model key is ""
    assert "" in result["models"]
    m = result["models"][""]
    assert m["cost"] == 0.0
    assert m["calls"] == 1
    assert m["input_tokens"] == 5000
    assert m["cache_read_tokens"] == 15000
    # cache_hit_pct: 15000 / (5000+15000) = 75%
    assert m["cache_hit_pct"] == 75.0


@pytest.fixture()
def fallback_model_session(tmp_path, monkeypatch):
    """Session where per-call model is empty but session model is set."""
    call_data = {
        "model": "claude-opus-4-6",
        "system_prompt_tokens": 3000,
        "calls": [
            {
                "turn": 1,
                "model": "",
                "timestamp": 1000.0,
                "api_input_tokens": 8000,
                "api_output_tokens": 2000,
                "api_cache_read": 6000,
                "api_cache_create": 500,
                "items": [],
            },
        ],
    }
    monkeypatch.setattr(
        "bouzecode.web_v2.services.sessions.costs.extract_per_call_data",
        lambda path: call_data,
    )
    return tmp_path / "session.json"


def test_session_costs_model_fallback(fallback_model_session):
    """When per-call model is empty, falls back to session-level model."""
    result = session_costs(str(fallback_model_session))
    assert result is not None
    assert "unpriced" not in result
    # Should be bucketed under the session model, not ""
    assert "claude-opus-4-6" in result["models"]
    assert "" not in result["models"]
    m = result["models"]["claude-opus-4-6"]
    assert m["cost"] > 0
    assert m["calls"] == 1
