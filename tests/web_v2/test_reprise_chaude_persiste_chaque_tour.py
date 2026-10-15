# [desc] Après une réponse à une question en pause CHAUDE, chaque tour repris est écrit dans la session sur disque dès qu'il se termine — le fil web l'empile en direct au lieu de ne montrer que le streaming du tour courant. [/desc]
"""TODO 2026-09-25 §3 — « les tours de réflexion successifs s'écrasent à l'affichage ».

Symptôme : quand le modèle enchaîne plusieurs tours, le tour n+1 REMPLACE le tour n pendant
la réflexion, et ce jusqu'à la FinalAnswer, où tout l'historique réapparaît d'un coup.

Cause : le fil web ne connaît que deux sources — `/blocks` (la session JSON sur disque) et
`/partial` (le tour en cours). La boucle principale de `repl.run_query` écrit la session à
chaque frontière de tour (`TurnDone`, `ToolEnd`, `CheckpointReady`). Mais un agent web qui
pose une question (AskUserQuestion, plan à valider) reste CHAUD : la reprise se joue dans
`repl._resume_paused_warm`, qui vidait le générateur (`for _ in gen: pass`) sans rien
écrire. Tous les tours d'après la réponse n'existaient donc que dans `/partial` — chaque
tour effaçant le précédent — jusqu'à la clôture (`_fire_completion` écrit la session).

Le test joue une reprise chaude réelle (`_resume_paused_warm`, fichiers IPC, `answer.txt`)
avec une reprise scriptée à la façon de la boucle : au début du 2ᵉ tour, la session lue
comme la lit `/blocks` (`store.load_session_json`) doit déjà contenir le 1ᵉʳ tour.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.agent import loop as loop_mod
from bouzecode.backend.agent.state import AgentState, CheckpointReady, ToolEnd, TurnDone
from bouzecode.backend.core import config as core_config
from bouzecode.backend.tools.interaction import PausedForInput
from bouzecode.ui import repl
from bouzecode.web_v2.runtime import ipc
from bouzecode.web_v2.services.sessions import store


def _tour(state: AgentState, n: int) -> None:
    state.messages.append({
        "role": "assistant",
        "content": f"<thinking>\nRéflexion du tour {n}\n</thinking>\n\nTour {n}.",
        "tool_calls": [{"id": f"b{n}", "name": "Bash", "input": {"command": f"echo {n}"}}],
    })


def _resultat(state: AgentState, n: int) -> None:
    state.messages.append({"role": "tool", "tool_call_id": f"b{n}", "name": "Bash", "content": str(n)})


@pytest.fixture()
def reprise_chaude(tmp_path, monkeypatch):
    """Agent web en pause chaude sur une question, réponse déjà déposée dans answer.txt."""
    ipc_dir = tmp_path / "ipc"
    ipc_dir.mkdir()
    monkeypatch.setenv(ipc.ENV_IPC_DIR, str(ipc_dir))
    (ipc_dir / "answer.txt").write_text("PostgreSQL", encoding="utf-8")
    monkeypatch.setattr(core_config, "MR_SESSION_DIR", tmp_path / "mr_sessions")
    session = tmp_path / "agent.session.json"
    config = {
        "_session_file": str(session),
        "_session_path": str(tmp_path / "daily" / "session_120000_abcd.json"),
        "_session_id": "abcd",
        "model": "mock",
    }
    state = AgentState()
    state.messages.append({"role": "user", "content": "Choisis la base puis enchaîne."})
    pause = PausedForInput(question="Quelle base ?", options=[], allow_freetext=True,
                           ask_tc_id="q1", completed_results={}, pending_tcs=[])
    return state, config, pause, session


def test_chaque_tour_repris_est_sur_disque_avant_le_suivant(reprise_chaude, monkeypatch):
    state, config, pause, session = reprise_chaude
    vu_au_debut_du_tour: dict[int, list] = {}

    def reprise_scriptee(pending, answer, st, cfg, system_prompt, cancel_check=None):
        """Même séquence d'événements que la boucle réelle : réponse versée (checkpoint),
        puis pour chaque tour assistant → TurnDone → outils → ToolEnd."""
        st.messages.append({"role": "tool", "tool_call_id": "q1", "name": "AskUserQuestion",
                            "content": answer})
        yield CheckpointReady(len(st.messages))
        for n in (1, 2, 3):
            # Le modèle réfléchit au tour n : c'est ce que /blocks sert à cet instant.
            data = store.load_session_json(session) or {}
            vu_au_debut_du_tour[n] = data.get("messages") or []
            _tour(st, n)
            yield TurnDone(10, 5)
            _resultat(st, n)
            yield ToolEnd("Bash", str(n), tool_id=f"b{n}")

    monkeypatch.setattr(loop_mod, "resume_paused", reprise_scriptee)
    repl._resume_paused_warm(pause, state, config, "", None)

    def contenus(messages):
        return [m.get("content") for m in messages]

    # La réponse à la question est dans le fil avant même le premier tour repris.
    assert "PostgreSQL" in contenus(vu_au_debut_du_tour[1])
    # Tour 2 : le tour 1 (réflexion + appel) ET son résultat sont déjà servis par /blocks.
    au_tour_2 = vu_au_debut_du_tour[2]
    assert any("Réflexion du tour 1" in str(c) for c in contenus(au_tour_2)), contenus(au_tour_2)
    assert any(m.get("tool_call_id") == "b1" for m in au_tour_2)
    # Tour 3 : les deux tours précédents s'empilent, dans l'ordre.
    tours = [m["content"] for m in vu_au_debut_du_tour[3] if m.get("role") == "assistant"]
    assert [("Tour 1." in t, "Tour 2." in t) for t in tours] == [(True, False), (False, True)]
