# [desc] Payload réel sur deux tours d'une session (Anthropic XML/natif, OpenRouter natif) : tout ce qui précède le dernier point de cache (Anthropic) ou l'historique (OpenRouter : system + outils) est identique d'un tour à l'autre ; note, contexte de session et rappels viennent après. [/desc]
"""Stabilité du préfixe caché (correctifs point 2, docs/reduction_tokens/correctifs.md).

Le modèle lit tools → system → messages. Le cache Anthropic ne sert que si les octets qui
précèdent un point `cache_control` sont identiques d'un tour à l'autre. On rejoue deux tours
consécutifs par le VRAI pipeline (dispatch, conversion, client Anthropic, faux serveur SSE) :
note Methodology modifiée entre les deux, contexte de session ; puis on vérifie
- que le flux du tour 2 reprend à l'octet près celui du tour 1 jusqu'à son dernier point de
  cache (la note n'y fait que s'ajouter) ;
- que la note est hors du system et que le contenu variable (contexte de session, règle
  finale) n'entre pas dans la note (depuis le 2026-10-07 il précède son point de cache, en
  fin de system : il doit donc rester identique d'un tour à l'autre) ;
- que le budget de 4 points de cache est tenu.
Chemins couverts : protocole XML (défaut d'Opus sur un endpoint compatible), outils natifs
Anthropic, et OpenRouter natif (system strictement stable, outils en cache).
"""
from __future__ import annotations

import json

import pytest

from bouzecode.backend.core.context import build_stable_system_prompt
from tests.e2e_harness import bouzecode

_VARIABLES = ("# Contexte de session", "RAPPEL : chaque lot")


def _segments(req: dict) -> list[tuple[str, bool]]:
    """Le flux dans l'ordre de lecture du modèle : (texte, porte un point de cache)."""
    segs = [(json.dumps(t, ensure_ascii=False, sort_keys=True), bool(t.get("cache_control")))
            for t in req.get("tools") or []]
    system = req["system"] if isinstance(req["system"], list) else [{"text": req["system"]}]
    segs += [(b.get("text", ""), bool(b.get("cache_control"))) for b in system]
    for m in req["messages"]:
        blocs = m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
        segs += [(b.get("text") if b.get("type") == "text" else json.dumps(b, sort_keys=True),
                  bool(b.get("cache_control"))) for b in blocs]
    return segs


def _flux_et_dernier_point(req: dict) -> tuple[str, int]:
    flux, fin = "", 0
    for texte, cache in _segments(req):
        flux += texte
        fin = len(flux) if cache else fin
    return flux, fin


def _verifier_deux_tours(t1: dict, t2: dict) -> None:
    flux1, fin1 = _flux_et_dernier_point(t1)
    flux2, fin2 = _flux_et_dernier_point(t2)
    assert fin1 > 0 and fin2 > fin1, "la note grandit : le point de cache avance"
    assert flux2[:fin1] == flux1[:fin1], "préfixe caché du tour 1 modifié au tour 2"
    # Depuis le 2026-10-07 la note est en tête du premier message user (<working_notes>) : le
    # contexte de session et la règle finale, restés en fin de system, précèdent donc son point
    # de cache. Le cache de la note tient tant qu'ils restent identiques d'un tour à l'autre —
    # ce que l'égalité ci-dessus vérifie ; ils ne doivent simplement pas passer DANS la note.
    for req in (t1, t2):
        systeme = json.dumps(req["system"], ensure_ascii=False)
        assert "[METHODOLOGY" not in systeme, "la note a quitté le system"
        flux, fin = _flux_et_dernier_point(req)
        debut_note = flux.index("<working_notes>")
        for variable in _VARIABLES:
            position = flux.find(variable)
            assert position == -1 or position < debut_note or position >= fin, \
                f"{variable!r} dans la note"
        assert sum(cache for _, cache in _segments(req)) <= 4


def _meth(contenu: str, i: int) -> str:
    return f'<tool_use name="Methodology" id="m{i}"><param name="content">{contenu}</param></tool_use>'


def test_prefixe_stable_protocole_xml(monkeypatch):
    monkeypatch.setenv("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", "0")
    cfg = {"model": "claude-opus-5", "enforce_tests": False}
    result = bouzecode(
        ["Ajoute add(a, b) dans calc.py."],
        mock_api=[_meth("## Plan - [ ] lire calc.py", 1) + '<tool_use name="Bash" id="b1"><param name="command">echo a</param></tool_use>',
                  _meth("- [x] lire calc.py", 2) + '<tool_use name="Bash" id="b2"><param name="command">echo b</param></tool_use>',
                  "Fini."],
        config_overrides=cfg, system_prompt=build_stable_system_prompt(cfg))

    t1, t2 = result.recorded_requests[1:3]
    assert "tools" not in t2 and "[RAPPEL — à chaque tour]" not in json.dumps(t2, ensure_ascii=False)
    _verifier_deux_tours(t1, t2)


def test_prefixe_stable_outils_natifs(monkeypatch):
    monkeypatch.setenv("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", "1")
    cfg = {"model": "claude-opus-5", "enforce_tests": False}
    result = bouzecode(["Ajoute add(a, b) dans calc.py.", "Ajoute aussi sub(a, b)."],
                       mock_api=["Noté.", "Noté aussi."],
                       config_overrides=cfg, system_prompt=build_stable_system_prompt(cfg))

    t1, t2 = result.recorded_requests[:2]
    assert t2.get("tools"), "outils natifs : les schémas partent en tête"
    assert "RAPPEL : chaque lot" in json.dumps(t2["system"], ensure_ascii=False)
    _verifier_deux_tours(t1, t2)


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


def test_prefixe_stable_openrouter_natif_jusqu_a_l_historique(monkeypatch):
    """DeepSeek & co. : le chat template met les outils APRÈS le system. Le system doit donc
    être identique d'un tour à l'autre ; la note (qui grandit), le contexte de session et la
    règle finale vont dans des messages user, avant l'historique (essai du 24/09 : « cache
    raté » à presque chaque tour, le system changeant à la note)."""
    from bouzecode.backend.agent.providers.backends import dispatch, openrouter_stream
    from bouzecode.backend.context_manager import ContextState
    from bouzecode.backend.context_manager.methodology import methodology_tool
    from bouzecode.backend.core.tool_registry import get_tool_schemas

    session = _Session()
    monkeypatch.setattr(openrouter_stream, "_build_session", lambda: session)
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-test")
    note = ContextState()
    methodology_tool({"content": "## Plan\n- [ ] lire calc.py"}, {"_context_state": note})
    cfg = {"model": "deepseek-v4.1-flash", "_context_state": note}
    systeme = build_stable_system_prompt(cfg)
    historiques = [[{"role": "user", "content": "Ajoute add(a, b)."}],
                   [{"role": "assistant", "content": ".", "tool_calls": [
                       {"id": "b1", "name": "Bash", "input": {"command": "ls"}}]},
                    {"role": "tool", "tool_call_id": "b1", "name": "Bash", "content": "calc.py"}]]
    for i, messages in enumerate(historiques):
        list(dispatch.stream(cfg["model"], systeme, messages, get_tool_schemas(), cfg))
        methodology_tool({"content": f"- [x] étape {i}"}, {"_context_state": note})

    t1, t2 = session.envois
    assert t1["messages"][0] == t2["messages"][0], "system identique d'un tour à l'autre"
    assert t1["tools"] == t2["tools"]
    # Depuis le 2026-10-07 : la note ouvre le premier message user (<working_notes>), le
    # contexte de session suit dans le message d'après.
    note1, note2 = t1["messages"][1]["content"], t2["messages"][1]["content"]
    assert note1.startswith("<working_notes>\n[METHODOLOGY")
    fin_note1 = note1.index("\n</working_notes>")
    assert note2.startswith(note1[:fin_note1]), "la note ne fait que s'ajouter"
    assert "# Contexte de session" in t2["messages"][2]["content"]
    for variable in ("# Contexte de session", "RAPPEL : chaque lot", "[METHODOLOGY"):
        assert variable not in t2["messages"][0]["content"]
