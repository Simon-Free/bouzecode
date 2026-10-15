"""Proxy LLM demo : en-têtes X-Demo-* réellement émis par les clients, et seulement
vers le proxy ; politique de cache et outils natifs alignés sur le gateway.

Un serveur HTTP local capture les requêtes ; les clients réels (SDK Anthropic via
build_anthropic_client, streamer OpenAI-compatible via requests) sont pointés dessus.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.agent.providers import llm_proxy
from bouzecode.backend.agent.providers.backends import dispatch
from bouzecode.backend.agent.providers.backends.anthropic_client import build_anthropic_client
from bouzecode.backend.agent.providers.backends.openrouter_stream import stream_openrouter
from bouzecode.backend.agent.providers.backends.openrouter_transport import build_plain_session
from bouzecode.backend.agent.providers.registry import anthropic_endpoint_serves_native_tools

from .header_capture_server import HeaderCaptureServer


@pytest.fixture
def server(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.delenv("BOUZECODE_LLM_PROXY", raising=False)
    monkeypatch.delenv("BOUZECODE_LLM_PROXY_COMMENT", raising=False)
    with HeaderCaptureServer() as srv:
        yield srv.root, srv.captured


def _lower(headers: dict) -> dict:
    return {k.lower(): v for k, v in headers.items()}


CONFIG = {"_session_id": "sess-42", "_agent_name": "tui-agent"}


def test_anthropic_client_sends_demo_headers_to_proxy(server):
    root, captured = server
    base_url = f"{root}/llm-proxy/anthropic"
    client = build_anthropic_client("clp_test", base_url,
                                    default_headers=llm_proxy.proxy_headers(base_url, CONFIG))
    client.messages.create(model="claude-test", max_tokens=8,
                           messages=[{"role": "user", "content": "hi"}])
    req = captured[-1]
    headers = _lower(req["headers"])
    assert req["path"] == "/llm-proxy/anthropic/v1/messages"
    assert headers["x-api-key"] == "clp_test"
    assert headers["x-demo-source"] == "bouzecode"
    assert headers["x-demo-session"] == "sess-42"
    comment = headers["x-demo-comment"]
    assert "tui-agent" in comment and len(comment) <= 200


def test_anthropic_client_sends_nothing_new_off_proxy(server):
    root, captured = server
    base_url = f"{root}/anthropic"
    client = build_anthropic_client("k", base_url,
                                    default_headers=llm_proxy.proxy_headers(base_url, CONFIG))
    client.messages.create(model="claude-test", max_tokens=8,
                           messages=[{"role": "user", "content": "hi"}])
    assert not any(k.startswith("x-demo") for k in _lower(captured[-1]["headers"]))


def _drain_openai(base_url: str):
    gen = stream_openrouter("clp_test", "gpt-test", "sys",
                            [{"role": "user", "content": "hi"}], [], dict(CONFIG),
                            base_url=base_url, session_factory=build_plain_session,
                            send_reasoning=False, provider_label="test")
    for _ in gen:
        pass


def test_openai_compatible_stream_sends_demo_headers_to_proxy(server):
    root, captured = server
    _drain_openai(f"{root}/llm-proxy/openai/v1")
    req = captured[-1]
    headers = _lower(req["headers"])
    assert req["path"] == "/llm-proxy/openai/v1/chat/completions"
    assert headers["authorization"] == "Bearer clp_test"
    assert headers["x-demo-source"] == "bouzecode"
    assert headers["x-demo-session"] == "sess-42"
    assert "tui-agent" in headers["x-demo-comment"]


def test_openai_compatible_stream_off_proxy_has_no_demo_headers(server):
    root, captured = server
    _drain_openai(f"{root}/v1")
    assert not any(k.startswith("x-demo") for k in _lower(captured[-1]["headers"]))


def test_comment_is_ascii_and_capped(monkeypatch):
    monkeypatch.setenv("BOUZECODE_LLM_PROXY_COMMENT", "projet é " + "x" * 300)
    headers = llm_proxy.proxy_headers("https://portail/llm-proxy/anthropic", {})
    assert headers["X-Demo-Source"] == "bouzecode"
    assert "X-Demo-Session" not in headers
    assert len(headers["X-Demo-Comment"]) == 200
    assert headers["X-Demo-Comment"].isascii()


def test_recognition_by_path_or_env(monkeypatch):
    monkeypatch.delenv("BOUZECODE_LLM_PROXY", raising=False)
    assert llm_proxy.is_llm_proxy("https://portal.example.com/llm-proxy/anthropic")
    assert not llm_proxy.is_llm_proxy("https://llm-gateway.example.com")
    assert not llm_proxy.is_llm_proxy("https://openrouter.ai/api/v1")
    assert not llm_proxy.is_llm_proxy(None)
    monkeypatch.setenv("BOUZECODE_LLM_PROXY", "1")
    assert llm_proxy.is_llm_proxy("https://portal.example.com/ai/anthropic")


def test_cache_policy_proxy_matches_gateway(monkeypatch):
    monkeypatch.delenv("BOUZECODE_CACHE_TTL_1H", raising=False)
    proxy = "https://portal.example.com/llm-proxy/anthropic"
    assert dispatch._resolve_cache_control(proxy) == {"type": "ephemeral"}
    assert dispatch._resolve_cache_control(proxy) == dispatch._resolve_cache_control(
        "https://llm-gateway.example.com")
    assert dispatch._resolve_cache_control(None) == {"type": "ephemeral", "ttl": "1h"}
    monkeypatch.setenv("BOUZECODE_CACHE_TTL_1H", "1")
    assert dispatch._resolve_cache_control(proxy) == {"type": "ephemeral", "ttl": "1h"}


def test_cache_policy_follows_anthropic_base_url_env(monkeypatch):
    monkeypatch.delenv("BOUZECODE_CACHE_TTL_1H", raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://portal.example.com/llm-proxy/anthropic")
    url = dispatch.provider_base_url("anthropic")
    assert dispatch._resolve_cache_control(url) == {"type": "ephemeral"}


def test_proxy_serves_native_tools_like_gateway():
    assert anthropic_endpoint_serves_native_tools("https://portal.example.com/llm-proxy/anthropic")
    assert anthropic_endpoint_serves_native_tools("https://llm-gateway.example.com")
