"""FIX 1 — garantie forte de terminalité : un ticket enfant fraîchement dispatché
doit être VISIBLE (launching posé) AVANT tout retour au parent, sinon le parent
peut être finalisé alors que l'enfant n'a pas encore démarré (race des 14 s
observée sur le manager 94dfb6d7ceb4).

Repro : on stubbe `_launch` pour qu'il ne fasse RIEN (simule la fenêtre entre
create_ticket et l'add_run réel). Sur le code AVANT fix, `dispatch()` ne posait
pas `launching` → child_pending_launch()=False ET has_launched()=False →
l'enfant était invisible → should_wake_parent() finalisait le parent à tort.
"""
import threading

from bouzecode.web_v2.services.work import dispatch
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work import _persistence
from bouzecode.web_v2.services.work import wake


class _FakeAgent:
    def __init__(self, agent_id="child9012ab34"):
        self.agent_id = agent_id


def _wire(monkeypatch, tmp_path):
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path / "tickets")
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path / "tickets")
    project = {"slug": "p", "name": "Projet", "path": str(tmp_path)}
    monkeypatch.setattr(dispatch.projects, "list_projects", lambda: [project])
    monkeypatch.setattr(dispatch.projects, "find", lambda slug: project)
    monkeypatch.setattr(dispatch, "get_typology", lambda name, path: {"profile": "", "default_model": ""})
    monkeypatch.setattr(dispatch, "resolve_isolation",
                        lambda path, requested, needs_worktree=False: ("shared", "test", ""))


def _child_ticket(monkeypatch, tmp_path, defer):
    """Dispatch un enfant en stubbant _launch (ne fait RIEN → simule la fenêtre
    AVANT add_run). Renvoie le ticket enfant relu depuis le store."""
    _wire(monkeypatch, tmp_path)

    def fake_launch(*a, **k):
        # ne pose NI run NI rien (simule la fenêtre AVANT add_run), mais rend un
        # objet avec .agent_id car le chemin sync (defer=False) lit agent.agent_id.
        return _FakeAgent()

    monkeypatch.setattr(dispatch, "_launch", fake_launch)
    monkeypatch.setattr(dispatch, "_launch_bg", fake_launch)

    result = dispatch.dispatch("fais un truc", project_slug="p", typology="default",
                               parent="mgr123456789", defer=defer)
    ticket_id = result["ticket_id"]
    # relire depuis le store (source de vérité, pas l'objet en mémoire)
    rows = tickets_svc.list_tickets("p")
    child = next(t for t in rows if t["id"] == ticket_id)
    return child


def test_dispatched_child_is_launching_before_run_defer(monkeypatch, tmp_path):
    """defer=True : l'enfant porte `launching` dès le retour de dispatch (avant add_run)."""
    child = _child_ticket(monkeypatch, tmp_path, defer=True)
    assert wake.child_pending_launch(child) is True
    assert wake.has_launched(child) is False  # pas encore de run réel


def test_dispatched_child_is_launching_before_run_sync(monkeypatch, tmp_path):
    """defer=False (_launch stubé) : même garantie — launching posé synchrone."""
    child = _child_ticket(monkeypatch, tmp_path, defer=False)
    assert wake.child_pending_launch(child) is True


def test_parent_not_woken_while_child_launching(monkeypatch, tmp_path):
    """Conséquence directe : tant que l'enfant est `launching` (pas encore de run),
    should_wake_parent renvoie False → le parent NE peut PAS être finalisé.

    Contre-preuve : le MÊME ticket sans le flag `launching` (état bug) et sans run
    laisse la porte ouverte à la finalisation prématurée."""
    child = _child_ticket(monkeypatch, tmp_path, defer=True)
    sig = wake.children_signature([child])

    # État corrigé : launching posé → parent bloqué
    assert wake.should_wake_parent(True, [child], None, sig) is False

    # État bug (flag retiré, toujours aucun run) : l'enfant devient invisible et
    # ne bloque plus le réveil (démontre pourquoi le fix est nécessaire).
    bugged = {**child}
    bugged.pop("launching", None)
    assert wake.child_pending_launch(bugged) is False
    assert wake.has_launched(bugged) is False
