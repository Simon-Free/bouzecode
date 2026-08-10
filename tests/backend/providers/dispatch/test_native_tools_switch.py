# [desc] Which tool protocol the Anthropic path uses: the escape hatch, the default, and the forced-XML override. [/desc]
"""Le choix du protocole d'outils sur le chemin Anthropic.

Natif supprime toute la classe d'erreurs de parsing XML, mais c'est le chemin chaud de
chaque session : il est donc OFF par defaut et s'active explicitement par
BOUZECODE_ANTHROPIC_NATIVE_TOOLS=1. `config["xml_tools"]` prime sur tout.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.agent.providers.registry import model_uses_native_tools
from bouzecode.backend.agent.providers.backends.dispatch import stream
from bouzecode.backend.tools.schemas import TOOL_SCHEMAS


def _system_payload(monkeypatch, config):
    """The SystemPayload dispatch yields before any HTTP happens."""
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "fake-key")
    gen = stream(model="claude-opus-4-8", system="",
                 messages=[{"role": "user", "content": "Hello"}],
                 tool_schemas=TOOL_SCHEMAS, config=config)
    try:
        return next(gen)
    finally:
        gen.close()


@pytest.fixture(autouse=True)
def _clean_switch(monkeypatch):
    monkeypatch.delenv("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", raising=False)


def test_anthropic_uses_xml_by_default():
    """Sans rien regler, le chemin Anthropic reste sur le protocole XML."""
    assert model_uses_native_tools("claude-opus-4-8", {}) is False


def test_the_escape_hatch_turns_native_on(monkeypatch):
    monkeypatch.setenv("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", "1")
    assert model_uses_native_tools("claude-opus-4-8", {}) is True


def test_the_escape_hatch_can_force_xml_back(monkeypatch):
    """Repli sans redeploiement si la passerelle regressait."""
    monkeypatch.setenv("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", "0")
    assert model_uses_native_tools("claude-opus-4-8", {}) is False


def test_forced_xml_config_outranks_the_escape_hatch(monkeypatch):
    monkeypatch.setenv("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", "1")
    assert model_uses_native_tools("claude-opus-4-8", {"xml_tools": True}) is False


def test_native_mode_sends_schemas_and_drops_the_xml_tool_docs(monkeypatch):
    """Interrupteur ON : les schemas partent dans `tools`, et ce que dispatch controle
    (la doc XML des outils + l'exemple d'amorcage Methodology du premier tour) ne
    contient plus de `<tool_use>` — il enseignerait le protocole qu'on vient de quitter."""
    monkeypatch.setenv("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", "1")

    payload = _system_payload(monkeypatch, {})

    assert payload.tools, "les schemas doivent partir dans le parametre `tools`"
    assert {"name", "description", "input_schema"} <= set(payload.tools[0]), (
        "les schemas Anthropic portent input_schema, pas la forme OpenAI"
    )
    system_text = "\n\n".join(b["text"] for b in payload.system_blocks if b.get("text"))
    assert "## Methodology" not in system_text, "la doc XML des outils doit avoir disparu"
    assert "votre note ici" not in system_text, "l'amorcage Methodology ne doit plus etre en XML"


def test_base_prompt_should_not_teach_xml_in_native_mode(monkeypatch):
    """Le prompt de base suit le PROTOCOLE, pas le provider : en mode natif il
    n'enseigne plus le XML (`core/context.py` branche sur `model_uses_native_tools`)."""
    monkeypatch.setenv("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", "1")

    payload = _system_payload(monkeypatch, {})

    system_text = "\n\n".join(b["text"] for b in payload.system_blocks if b.get("text"))
    assert "<tool_use" not in system_text


def test_xml_mode_still_documents_the_protocol(monkeypatch):
    """Interrupteur OFF : la doc XML reste dans le prompt et rien ne part en `tools`."""
    monkeypatch.setenv("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", "0")

    payload = _system_payload(monkeypatch, {})

    assert payload.tools is None
    system_text = "\n\n".join(b["text"] for b in payload.system_blocks if b.get("text"))
    assert "<tool_use" in system_text


def test_openrouter_keeps_native_whatever_the_anthropic_switch_says(monkeypatch):
    """L'interrupteur ne concerne que le chemin Anthropic."""
    monkeypatch.setenv("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", "0")
    assert model_uses_native_tools("deepseek-v4-flash", {}) is True


# `base_url` is taken by the pytest-base-url plugin (session-scoped): naming the
# parameter `endpoint` avoids a ScopeMismatch at setup.
@pytest.mark.parametrize("endpoint,eligible", [
    ("https://api.anthropic.com", True),
    (None, True),
    ("https://un-proxy-inconnu.example", False),
])
def test_only_measured_endpoints_are_eligible_for_the_future_default(endpoint, eligible):
    """La table d'endpoints qui gouvernera le defaut quand il basculera : seuls les
    gateways effectivement mesures y figurent."""
    from bouzecode.backend.agent.providers.registry import (
        anthropic_endpoint_serves_native_tools,
    )
    assert anthropic_endpoint_serves_native_tools(endpoint) is eligible
