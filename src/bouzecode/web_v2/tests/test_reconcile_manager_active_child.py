"""Un manager (NON_CODING_TYPOLOGIES) qui rend une FinalAnswer à chaque tour clôt son
process GRACIEUSEMENT (close_reason=final_answer). À la reprise/tick, `_reconcile_graceful_close`
ne doit PAS le marquer `completed` tant qu'un enfant est encore ACTIF (lancé non-terminal ou en
cours de lancement) — sinon le manager est figé « Terminé » et n'est plus jamais réveillé pour
superviser/relancer l'enfant (orchestration gelée). Régression : deuxième symptôme observé sur un ticket réel.

Zero unittest.mock (interdit dans web_v2) : on pilote les dépendances de wake via monkeypatch.setattr,
comme les autres tests du dossier."""
from types import SimpleNamespace

from bouzecode.web_v2.services.work import wake


def _manager_ticket():
    """Ticket manager avec un run work mort/non-completed/sans verdict."""
    return {
        "id": "T-mgr",
        "typology": "manager",
        "runs": [{"agent_id": "mgr-1", "kind": "work"}],
    }


def _wire(monkeypatch, session_close_reason, children):
    """Branche wake sur un agent MORT dont la session porte `session_close_reason`,
    et sur la liste d'enfants `children`. Retourne la liste des appels mark_run_completed."""
    completed_calls: list[str] = []
    agent = SimpleNamespace(session_path="/does/not/matter.json", cwd="/tmp", ipc_dir="")
    monkeypatch.setattr(wake.runner, "load_agent", lambda aid: agent)
    monkeypatch.setattr(wake.runner, "is_running", lambda a: False)
    monkeypatch.setattr(wake.store, "load_session_json",
                        lambda p: {"close_reason": session_close_reason})
    monkeypatch.setattr(wake.web_deferred, "exists", lambda p: False)
    monkeypatch.setattr(wake, "_children_by_parent", lambda: {"mgr-1": children})
    monkeypatch.setattr(wake.tickets_svc, "mark_run_completed",
                        lambda slug, ticket, aid: completed_calls.append(aid))
    monkeypatch.setattr(wake.tickets_svc, "update_ticket", lambda slug, ticket: None)
    return completed_calls


def test_manager_not_completed_while_child_pending_launch(monkeypatch):
    # Enfant fraîchement (re)dispatché : `launching` posé, pas encore de run.
    child = {"id": "T-child", "parent": "mgr-1", "launching": True}
    completed = _wire(monkeypatch, "final_answer", [child])
    ticket = _manager_ticket()

    wake._reconcile_graceful_close("proj", ticket)

    # Garde active : le manager reste RÉVEILLABLE, jamais figé « Terminé ».
    assert completed == [], "le manager ne doit PAS être marqué completed tant qu'un enfant démarre"


def test_manager_not_completed_while_child_running(monkeypatch):
    # Enfant lancé (a un run) et NON terminal (busy).
    child = {"id": "T-child", "parent": "mgr-1", "runs": [{"agent_id": "kid-1", "kind": "work"}]}
    monkeypatch.setattr(wake.workflow, "derive_state", lambda t: "busy")
    completed = _wire(monkeypatch, "final_answer", [child])
    ticket = _manager_ticket()

    wake._reconcile_graceful_close("proj", ticket)

    assert completed == [], "le manager ne doit PAS être marqué completed tant qu'un enfant tourne"


def test_manager_completed_when_all_children_terminal(monkeypatch):
    # Non-régression : tous les enfants sont terminaux → le manager DOIT devenir finalisable
    # (mark_run_completed appelé pour que _finalize_noncoding_parent le clôture ensuite).
    child = {"id": "T-child", "parent": "mgr-1", "runs": [{"agent_id": "kid-1", "kind": "work"}]}
    # derive_state != busy ET reaper.terminal_outcome non None → ticket_terminal True.
    monkeypatch.setattr(wake.workflow, "derive_state", lambda t: "integrated")
    monkeypatch.setattr(wake.reaper, "terminal_outcome", lambda t: "integrated")
    completed = _wire(monkeypatch, "final_answer", [child])
    ticket = _manager_ticket()

    wake._reconcile_graceful_close("proj", ticket)

    assert completed == ["mgr-1"], "manager finalisable quand tous les enfants sont terminaux"


def test_manager_completed_when_no_children(monkeypatch):
    # Non-régression : aucun enfant → rien à superviser → finalisable.
    completed = _wire(monkeypatch, "final_answer", [])
    ticket = _manager_ticket()

    wake._reconcile_graceful_close("proj", ticket)

    assert completed == ["mgr-1"], "manager sans enfant doit être finalisable"
