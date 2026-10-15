from bouzecode.backend.core.config import has_api_key, missing_key_hint


def test_gateway_preprod_hint_names_its_own_env_var(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY_PP", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "prod-key")
    cfg = {"model": "claude-opus-5-5"}
    assert not has_api_key(cfg)
    hint = missing_key_hint(cfg)
    assert "OPENAI_API_KEY_PP" in hint
    assert "gateway_preprod_api_key" in hint
    assert "ANTHROPIC_API_KEY" not in hint


def test_gateway_preprod_key_from_env_is_found(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY_PP", "pp-key")
    assert has_api_key({"model": "claude-opus-5-5"})
