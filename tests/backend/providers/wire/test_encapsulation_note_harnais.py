# [desc] Requête finale (OpenAI-compatible et Anthropic) : la note Methodology part en tête du premier message user dans <working_notes>, les consignes du harnais quittent les tool_results pour un bloc <harness_notes> placé après eux. [/desc]
"""Refus `content_filter` de claude-opus-5-5 (préprod du gateway), rejeu des payloads réels du
2026-10-07, 10 essais par variante : tour 9 de bb991b7c 10/10 refus → note dans le user 3/10
→ et consignes du harnais hors des tool_results 0/10 ; tour 13 de 4802718c 8/10 → 0/10.
Un texte écrit par le modèle (la note) en rôle system et des consignes déguisées en données
d'outil ressemblent à une injection : on les met, balisés, côté user (comme Claude Code).

Fixture : session 4802718c, enregistrement 25 (tour 13), Read élargi à 60 lignes pour que le
résultat soit « à snippeter ». On rejoue le VRAI chemin (fil minimal, dispatch, conversion)
jusqu'à la requête HTTP, interceptée sans réseau.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from bouzecode.backend.agent.demande_en_cours import DEMANDE_UTILISATEUR
from bouzecode.backend.agent.minimal_payload import build_messages_for_api
from bouzecode.backend.agent.providers.backends import (
    anthropic_stream, dispatch, openrouter_stream, openrouter_transport,
)
from bouzecode.backend.context_manager import ContextState
from bouzecode.backend.context_manager.state import METHODOLOGY_NOTE
from bouzecode.backend.core.tool_registry import get_tool_schemas
from tests import cache_conversation_helpers as cch
from tests.backend.providers.test_anthropic_empty_completion import FakeStreamCtx, _events

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "session_4802718c_t13.json")
                     .read_text("utf-8"))
READ_ID = next(t["id"] for t in FIXTURE["tools"] if t["name"] == "Read")
CONSIGNES = ("[SYSTEM]", "A SNIPPETER", "Verbatim tool_results")


class _Flux:
    ok, status_code, encoding, text = True, 200, "utf-8", ""

    def iter_lines(self, decode_unicode=False):
        yield 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1}}'
        yield "data: [DONE]"


class _Session:
    def __init__(self) -> None:
        self.envois: list[dict] = []

    def post(self, url, **kw):
        self.envois.append(kw["json"])
        return _Flux()


def _etat(note: str, snapshot: str) -> SimpleNamespace:
    tools = FIXTURE["tools"]
    messages = [
        {"role": "user", "content": FIXTURE["demande"], DEMANDE_UTILISATEUR: True},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": t["id"], "name": t["name"], "input": t["input"]} for t in tools]},
        *({"role": "tool", "tool_call_id": t["id"], "name": t["name"], "content": t["content"]}
          for t in tools),
    ]
    context_state = ContextState()
    if note:
        context_state.notes[METHODOLOGY_NOTE] = note
    context_state._methodology_cache_snapshot = snapshot
    return SimpleNamespace(messages=messages, context_state=context_state)


def _requete(monkeypatch, transport: str, note: str = FIXTURE["note"],
             snapshot: str = FIXTURE["snapshot"]) -> dict:
    """La requête finale du transport, telle qu'elle partirait sur le réseau."""
    etat = _etat(note, snapshot)
    envois: list[dict] = []
    if transport == "openai":
        model = "claude-opus-5-5"
        monkeypatch.setenv("OPENAI_API_KEY_PP", "sk-test")
        monkeypatch.setenv("PREPROD_ENDPOINT", "http://gateway.invalid")
        session = _Session()
        monkeypatch.setattr(openrouter_transport, "build_plain_session", lambda: session)
        envois = session.envois
    elif transport == "gpt":
        model = "deepseek-v4.1-flash"
        monkeypatch.setenv("OPENROUTER_KEY", "sk-or-test")
        session = _Session()
        monkeypatch.setattr(openrouter_stream, "_build_session", lambda: session)
        envois = session.envois
    else:
        model = "claude-opus-5"
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", "1" if transport == "anthropic" else "0")
        # Client et création du flux remplacés ci-dessous : aucun appel réseau possible, on
        # lève donc la garde de conftest qui bloque tout passage par stream_anthropic.
        monkeypatch.setattr(cch, "LIVE_API_ALLOWED", True)
        monkeypatch.setattr(anthropic_stream, "build_anthropic_client", lambda *a, **k: object())

        def _enregistrer(client, kwargs):
            envois.append(kwargs)
            return FakeStreamCtx(_events("ok"))
        monkeypatch.setattr(anthropic_stream, "_create_anthropic_stream_with_retry", _enregistrer)
    config = {"model": model, "_context_state": etat.context_state}
    wire = build_messages_for_api(etat, config)
    list(dispatch.stream(model, "Tu es bouzecode.", wire, get_tool_schemas(), config))
    return envois[0]


def _parties(content) -> list[dict]:
    return content if isinstance(content, list) else [{"type": "text", "text": content}]


def _system(req: dict) -> list[dict]:
    if "system" in req:
        return _parties(req["system"])
    return _parties(req["messages"][0]["content"])


def _users(req: dict) -> list[dict]:
    return [m for m in req["messages"] if m["role"] == "user"]


def _resultats(req: dict) -> list[str]:
    """Le contenu de chaque tool_result, quel que soit le transport."""
    oai = [m["content"] for m in req["messages"] if m["role"] == "tool"]
    natifs = [json.dumps(b["content"], ensure_ascii=False) for m in _users(req)
              for b in _parties(m["content"]) if b.get("type") == "tool_result"]
    textes = "".join(b.get("text", "") for m in _users(req) for b in _parties(m["content"]))
    xml = re.findall(r"<tool_result .*?</tool_result>", textes, re.DOTALL)
    return oai + natifs + xml


def _notes_du_harnais(req: dict) -> str:
    """Le bloc <harness_notes> : bloc text en fin du message user des tool_result (Anthropic),
    ou message user qui suit les messages `tool` (OpenAI)."""
    messages = req["messages"]
    if any(m["role"] == "tool" for m in messages):
        dernier = max(i for i, m in enumerate(messages) if m["role"] == "tool")
        suivant = messages[dernier + 1]
        assert suivant["role"] == "user"
        return "".join(p.get("text", "") for p in _parties(suivant["content"]))
    porteur = next(m for m in messages if m["role"] == "user" and any(
        b.get("type") == "tool_result" for b in _parties(m["content"])))
    dernier_bloc = _parties(porteur["content"])[-1]
    assert dernier_bloc["type"] == "text"
    return dernier_bloc["text"]


TRANSPORTS = ["openai", "anthropic"]


@pytest.mark.parametrize("transport", TRANSPORTS + ["anthropic_xml", "gpt"])
def test_aucun_bloc_system_ne_porte_la_note(monkeypatch, transport):
    req = _requete(monkeypatch, transport)
    assert not any("[METHODOLOGY" in p.get("text", "") for p in _system(req))
    assert not any("### T12" in p.get("text", "") for p in _system(req)), "delta de la note"


@pytest.mark.parametrize("transport", TRANSPORTS + ["anthropic_xml"])
def test_premier_message_user_commence_par_la_note_cachee(monkeypatch, transport):
    req = _requete(monkeypatch, transport)
    premier = req["messages"][1 if transport == "openai" else 0]
    assert premier["role"] == "user"
    parties = _parties(premier["content"])
    texte = "".join(p.get("text", "") for p in parties)
    assert texte.startswith("<working_notes>\n[METHODOLOGY")
    assert "### T12" in texte and texte.index("</working_notes>") > texte.index("### T12")
    assert FIXTURE["demande"][:60] in texte[texte.index("</working_notes>"):]
    note_cachee = "".join(p["text"] for p in parties if p.get("cache_control"))
    assert note_cachee.startswith("<working_notes>\n[METHODOLOGY") and "### T12" in note_cachee


@pytest.mark.parametrize("transport", TRANSPORTS + ["anthropic_xml", "gpt"])
def test_aucun_tool_result_ne_porte_de_consigne_du_harnais(monkeypatch, transport):
    resultats = _resultats(_requete(monkeypatch, transport))
    assert len(resultats) == 3
    for resultat in resultats:
        assert not any(c in resultat for c in CONSIGNES), resultat[:300]


@pytest.mark.parametrize("transport", TRANSPORTS + ["gpt"])
def test_notes_du_harnais_apres_les_resultats(monkeypatch, transport):
    notes = _notes_du_harnais(_requete(monkeypatch, transport))
    assert notes.startswith("<harness_notes>") and notes.rstrip().endswith("</harness_notes>")
    assert READ_ID in notes and "Snippet(" in notes and "discard" in notes
    for outil in FIXTURE["tools"]:
        assert outil["id"] in notes, "inventaire des résultats encore en contexte"


@pytest.mark.parametrize("transport", TRANSPORTS + ["anthropic_xml"])
def test_au_plus_quatre_points_de_cache(monkeypatch, transport):
    req = _requete(monkeypatch, transport)
    assert json.dumps(req, ensure_ascii=False).count('"cache_control"') <= 4


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_note_vide_le_rappel_d_amorce_part_aussi_dans_le_user(monkeypatch, transport):
    req = _requete(monkeypatch, transport, note="", snapshot="")
    assert not any("[METHODOLOGY" in p.get("text", "") for p in _system(req))
    premier = req["messages"][1 if transport == "openai" else 0]
    texte = "".join(p.get("text", "") for p in _parties(premier["content"]))
    assert texte.startswith("<working_notes>\n[METHODOLOGY") and "Note vide" in texte
