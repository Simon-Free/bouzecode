# [desc] Tests du réglage unique de thinking : résolution du niveau, paramètres API par modèle, refus masqué. [/desc]
"""Réglage de thinking (incident claude-opus-5 du 2026-09-28/29).

Les réponses vides d'Opus 5 étaient des refus du classifieur, déclenchés par les consignes
de <thinking> manuel et masqués en `end_turn` vide par le proxy LiteLLM du gateway.
"""
import pytest

from bouzecode.backend.agent.providers.thinking_level import (
    DEFAULT_LEVEL, anthropic_thinking_params, is_masked_refusal, resolve_thinking_level,
)


def test_default_level_is_medium(monkeypatch):
    monkeypatch.delenv("BOUZECODE_THINKING", raising=False)
    assert resolve_thinking_level({}) == DEFAULT_LEVEL == "medium"


def test_config_level_wins_over_env(monkeypatch):
    monkeypatch.setenv("BOUZECODE_THINKING", "low")
    assert resolve_thinking_level({"thinking_level": "high"}) == "high"


def test_env_level_used_when_config_is_silent(monkeypatch):
    monkeypatch.setenv("BOUZECODE_THINKING", "xhigh")
    assert resolve_thinking_level({}) == "xhigh"


@pytest.mark.parametrize("side_call_config", [
    {"thinking_mode": "off", "thinking_level": "high"},
    {"thinking": False, "thinking_level": "high"},
])
def test_side_calls_that_switch_thinking_off_get_none(side_call_config):
    assert resolve_thinking_level(side_call_config) == "none"


def test_unknown_level_is_rejected():
    with pytest.raises(ValueError, match="none, low, medium, high, xhigh, max"):
        resolve_thinking_level({"thinking_level": "extreme"})


def test_opus_5_levels_become_adaptive_thinking_with_effort():
    assert anthropic_thinking_params("claude-opus-5", "medium") == {
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": "medium"},
    }


def test_opus_5_none_disables_thinking():
    assert anthropic_thinking_params("claude-opus-5", "none") == {"thinking": {"type": "disabled"}}


def test_models_that_cannot_disable_thinking_fall_back_to_low_effort():
    assert anthropic_thinking_params("claude-opus-5-5", "none") == {
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": "low"},
    }


def test_sonnet_5_5_none_uses_between_tools():
    assert anthropic_thinking_params("claude-sonnet-5-5", "none") == {
        "thinking": {"type": "between_tools"}}


def test_models_without_adaptive_thinking_get_no_parameter():
    assert anthropic_thinking_params("claude-haiku-4-5-20251001", "high") == {}


def test_provider_prefix_is_ignored():
    assert anthropic_thinking_params("anthropic/claude-opus-5", "none") == {
        "thinking": {"type": "disabled"}}


def test_empty_end_turn_with_a_few_tokens_is_a_masked_refusal():
    # Mesuré au rejeu : end_turn, un bloc text vide, 1 à 9 tokens ; la route
    # /v1/chat/completions du même proxy rend content_filter pour la même requête.
    assert is_masked_refusal(stop_reason="end_turn", produced_text="", tool_calls=[],
                             had_thinking=False, out_tokens=7)


@pytest.mark.parametrize("overrides", [
    {"produced_text": "OK"},
    {"tool_calls": [{"name": "Bash"}]},
    {"had_thinking": True},
    {"out_tokens": 400},
    {"stop_reason": "max_tokens"},
])
def test_anything_actually_produced_is_not_a_refusal(overrides):
    turn = {"stop_reason": "end_turn", "produced_text": "", "tool_calls": [],
            "had_thinking": False, "out_tokens": 7, **overrides}
    assert not is_masked_refusal(**turn)
