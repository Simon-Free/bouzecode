# [desc] <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests cache_control TTL resolution logic for official vs non-official Anthropic endpoints with env flag</param></tool_use> [/desc]
from bouzecode.backend.agent.providers.backends.dispatch import _resolve_cache_control

NON_OFFICIAL = "https://proxy.llm.internal"


def test_official_anthropic_always_has_ttl_1h(monkeypatch):
    monkeypatch.delenv("BOUZECODE_CACHE_TTL_1H", raising=False)
    assert _resolve_cache_control("https://api.anthropic.com") == {"type": "ephemeral", "ttl": "1h"}
    assert _resolve_cache_control(None) == {"type": "ephemeral", "ttl": "1h"}


def test_non_official_without_flag_has_no_ttl(monkeypatch):
    monkeypatch.delenv("BOUZECODE_CACHE_TTL_1H", raising=False)
    assert _resolve_cache_control(NON_OFFICIAL) == {"type": "ephemeral"}


def test_non_official_with_flag_gets_ttl_1h(monkeypatch):
    monkeypatch.setenv("BOUZECODE_CACHE_TTL_1H", "1")
    assert _resolve_cache_control(NON_OFFICIAL) == {"type": "ephemeral", "ttl": "1h"}


def test_flag_zero_means_off(monkeypatch):
    monkeypatch.setenv("BOUZECODE_CACHE_TTL_1H", "0")
    assert _resolve_cache_control(NON_OFFICIAL) == {"type": "ephemeral"}
