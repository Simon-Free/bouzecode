# [desc] Une nouvelle session (/clear) ou un nouveau tour n'hérite jamais de la clôture précédente. [/desc]
"""Fuite d'état de clôture entre deux sessions du même TUI.

Poste Windows, 2026-09-09 et 2026-09-21 : les sessions 001c222b et 6dc8170b ont été
enregistrées avec `close_reason=final_answer` et le `final_answer` de la session
PRÉCÉDENTE (9026e6d8, 6c1e0ed4) — alors qu'elles ne s'étaient jamais closes (Ctrl+C en
plein lot, dernier message = un appel d'outils sans résultat). `/clear` remettait à zéro
messages, compteurs et note, mais pas un seul champ de clôture : le même `AgentState`
portait donc la clôture de la conversation d'avant dans la suivante.
"""
from __future__ import annotations

import dataclasses

from bouzecode.backend.agent.loop import run
from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.commands.core.basic import cmd_clear
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
REPONSE_9026 = "## 1. `decision` : un seul champ, trois encodages selon la couche"
FINAL = ('<tool_use name="FinalAnswer" id="f1">'
         f'<param name="answer">{REPONSE_9026}</param>'
         '<param name="taches_terminees">["expliquer decision"]</param>'
         '<param name="taches_restantes">[]</param></tool_use>')

# Champs que run() repose lui-même à chaque tour : leur valeur après /clear est sans enjeu.
_REPOSES_PAR_RUN = {"system_prompt", "bouzecode_commit", "bouzecode_version", "profile",
                    "run_kind"}


def _session_close():
    """La session 9026e6d8 : un vrai tour, clos par FinalAnswer."""
    return bouzecode(["regarde decision"], mock_llm=MockLLM([f"{METH}\n{FINAL}"]))


def test_clear_ne_laisse_rien_de_la_cloture_precedente(tmp_path, monkeypatch):
    # /clear enregistre d'abord la session qui s'achève (sessions/daily, figé à l'import).
    monkeypatch.setattr("bouzecode.backend.core.config.DAILY_DIR", tmp_path)
    state = _session_close().state
    assert state.close_reason == "final_answer" and state.final_answer == REPONSE_9026

    cmd_clear("", state, {"model": "test"})

    neuf = AgentState()
    restes = {
        f.name: getattr(state, f.name) for f in dataclasses.fields(AgentState)
        if f.name not in _REPOSES_PAR_RUN and f.name != "context_state"
        and getattr(state, f.name) != getattr(neuf, f.name)
    }
    assert restes == {}, f"/clear a laissé l'état de la session précédente : {restes}"
    assert state.context_state.notes == {} and state.context_state.deferred_queue == []
    assert state.context_state == neuf.context_state, "chaque champ de context_state remis à neuf"


def test_une_verification_differee_ne_survit_pas_au_clear():
    """Une suite différée de la session d'avant partirait à la clôture de la suivante."""
    state = AgentState()
    state.context_state.deferred_queue.append({"command": "pytest", "timeout": 900})
    cmd_clear("", state, {"model": "test"})
    assert state.context_state.deferred_queue == []


def test_un_nouveau_tour_ne_porte_plus_le_motif_de_la_cloture_precedente():
    """001c222b : le tour suivant est interrompu en plein lot (Ctrl+C) — sans clôture.

    L'enregistrement de ce moment-là ne doit pas dire « final_answer » : ce motif était
    celui d'un tour fini, pas de celui qui tourne."""
    state = _session_close().state
    assert state.close_reason == "final_answer"

    gen = run("il y a toujours un problème avec le parser", state,
              {"model": "test", "permission_mode": "accept-all"}, "sys")
    next(gen)  # le message utilisateur est posé, le tour démarre (CheckpointReady)
    gen.close()  # Ctrl+C avant toute clôture

    assert state.close_reason == ""
    assert state.close_detail == ""
