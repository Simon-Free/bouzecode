# [desc] Parler a un agent VIVANT dont la fiche porte un pid perime (409 not_delivered). [/desc]
"""Le Bureau envoie un message a son assistant : POST …/tickets/<id>/messages -> 409 CONFLICT.

La fiche de l'agent (`web_agents/<id>.json`) porte un `pid` qui ne correspond plus au
process reellement vivant pour cette session (process warm relance hors fiche, pid
recycle...). Deux gardes jugent alors la MEME question avec deux mesures differentes :

  * la garde CHAUDE (`_is_warm` / `_is_warm_awaiting`) teste `psutil.pid_exists(agent.pid)`
    -> FAUX, donc pas de reprise chaude ;
  * la garde FROIDE (`_respawn`) teste `_session_process_running(session_path)` par
    CMDLINE -> VRAI, donc elle refuse de lancer un jumeau et rend None.

Ni chaud ni froid : le message tombe dans un TROU NOIR, `send_to_ticket_agent` repond
409 `not_delivered`, et `bureau_assistant.js` retente toutes les 4 s a l'infini.
Le process est VIVANT et joignable : le message doit PARTIR (followup.txt pousse).
"""
from __future__ import annotations

import pytest

from bouzecode.web_v2.runtime import ipc, pending
from bouzecode.web_v2.runtime.runner import (
    agent_etat,
    agent_fiche,
    agent_processus,
    agent_reprise,
    agent_vivacite,
)
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import delivery, dispatch, messaging, tickets

PID_PERIME = 424242      # pid inscrit dans la fiche : ce process n'existe plus
PID_VIVANT = 313131      # pid du process reellement en vie pour cette session


class _ProcVivant:
    """Sosie de psutil.Process tel que `_procs_for_session` en rend."""

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def is_running(self) -> bool:
        return True


@pytest.fixture()
def bureau_pid_perime(monkeypatch, tmp_path):
    """Agent dont la fiche porte un pid mort alors qu'un process vit pour la session.

    Renvoie (agent, journal) : `journal` liste les effets de bord observes.
    """
    journal: list[tuple[str, str]] = []
    ipc_dir = tmp_path / "ipc"
    ipc_dir.mkdir()
    agent = agent_fiche.Agent(agent_id="a1", prompt="p", model="", cwd=str(tmp_path),
                         pid=PID_PERIME, started_at="",
                         session_path=str(tmp_path / "a1.session.json"),
                         ipc_dir=str(ipc_dir))

    # --- couche systeme : le pid de la fiche est mort, un process vit sur la session ---
    monkeypatch.setattr(agent_vivacite.psutil, "pid_exists", lambda pid: pid == PID_VIVANT)
    monkeypatch.setattr(agent_processus, "_procs_for_session",
                        lambda session_path: [_ProcVivant(PID_VIVANT)])
    # Le process a fini son dernier tour : l'IPC dit `finished` (fenetre post-FinalAnswer).
    monkeypatch.setattr(agent_etat, "get_ipc_state", lambda a: {"status": "finished"})
    monkeypatch.setattr(agent_fiche, "_save", lambda a: journal.append(("save", str(a.pid))))

    # --- resolution du ticket / de l'agent ---
    monkeypatch.setattr(agent_fiche, "load_agent", lambda aid: agent if aid == "a1" else None)
    ticket = {"id": "T1", "runs": [{"kind": "work", "agent_id": "a1"}]}
    monkeypatch.setattr(messaging, "resolve_ticket",
                        lambda tid: ("bouzecode", ticket) if tid == "T1" else None)
    monkeypatch.setattr(tickets, "get_ticket",
                        lambda slug, tid: ticket if (slug, tid) == ("bouzecode", "T1") else None)
    # La fiche a un pid mort -> `runner.is_running` est faux -> store classe `finished`.
    monkeypatch.setattr(store, "agent_status", lambda a: {"state": "finished"})
    monkeypatch.setattr(store, "invalidate_status", lambda aid: None)
    monkeypatch.setattr(pending, "exists", lambda sp: False)

    # --- ecritures de bord neutralisees / observees ---
    monkeypatch.setattr(dispatch, "rehome_agent_cwd",
                        lambda a: journal.append(("rehome", "")) or a.cwd)
    monkeypatch.setattr(delivery, "reopen_for_new_work", lambda slug, tid: None)
    monkeypatch.setattr(tickets, "add_comment",
                        lambda slug, t, text, human: journal.append(("comment", text)))
    return agent, journal


def _poster(text: str):
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client().post("/api/projects/bouzecode/tickets/T1/messages",
                                 json={"text": text, "mode": "queue"})


def test_le_message_part_vers_le_process_vivant_malgre_un_pid_de_fiche_perime(
        bureau_pid_perime):
    """Point d'entree utilisateur : le clic « Envoyer » du /bureau ne doit pas 409."""
    agent, journal = bureau_pid_perime
    reponse = _poster("relis le doc")
    assert reponse.status_code == 200, reponse.get_data(as_text=True)
    # Le message est REELLEMENT parti : le process vivant le trouvera dans followup.txt.
    paths = ipc.from_dir(agent.ipc_dir)
    assert paths.followup.exists(), journal
    assert paths.followup.read_text(encoding="utf-8") == "relis le doc"
    # Et il est journalise en commentaire du ticket (un envoi reussi se dit).
    assert ("comment", "relis le doc") in journal, journal


def test_on_ne_reisole_pas_le_worktree_sous_un_process_vivant(bureau_pid_perime):
    """`rehome_agent_cwd` changerait le worktree sous les pieds d'un agent en vie."""
    _agent, journal = bureau_pid_perime
    _poster("relis le doc")
    assert ("rehome", "") not in journal, journal


def test_le_pid_de_la_fiche_est_resynchronise_sur_le_process_reel(bureau_pid_perime):
    """Sans resynchro, le prochain envoi retomberait dans le meme trou noir."""
    agent, _journal = bureau_pid_perime
    _poster("relis le doc")
    assert agent.pid == PID_VIVANT


def test_un_echec_de_remise_dit_son_motif_machine_au_front(monkeypatch):
    """`reason` doit traverser la route : le front distingue « il reflechit » d'un envoi perdu."""
    ticket = {"id": "T1", "runs": [{"kind": "work", "agent_id": "a1"}]}
    agent = agent_fiche.Agent(agent_id="a1", prompt="p", model="", cwd="/live", pid=1,
                         started_at="", session_path="/tmp/a1.session.json")
    monkeypatch.setattr(messaging, "resolve_ticket", lambda tid: ("bouzecode", ticket))
    monkeypatch.setattr(tickets, "get_ticket", lambda slug, tid: ticket)
    monkeypatch.setattr(tickets, "add_comment", lambda slug, t, text, human: None)
    monkeypatch.setattr(agent_fiche, "load_agent", lambda aid: agent)
    monkeypatch.setattr(store, "agent_status", lambda a: {"state": "finished"})
    monkeypatch.setattr(agent_processus, "session_process_running", lambda path: True)
    monkeypatch.setattr(pending, "exists", lambda path: False)
    monkeypatch.setattr(delivery, "reopen_for_new_work", lambda slug, ticket_id: None)
    monkeypatch.setattr(agent_reprise, "continue_agent", lambda a, text, **_: None)   # jumeau refusé
    reponse = _poster("relis le doc")
    assert reponse.status_code == 409
    assert reponse.get_json()["error"]["code"] == "not_delivered", reponse.get_json()
