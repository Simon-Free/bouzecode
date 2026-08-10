"""Un ticket EN COURS DE LANCEMENT (worktree+venv+spawn en fond) n'a pas encore
d'agent → invisible de runner.list_agents(). Il doit apparaître comme node
synthétique state="provisioning" dans l'arbre agents, pour que l'UI Conversations
montre IMMÉDIATEMENT l'entrée (sidebar + onglet « worktree en création »),
au lieu du délai perçu où rien ne s'affiche pendant plusieurs secondes.

Fakes purs (monkeypatch) : on contrôle les dépendances de fleet
(runner.list_agents, store, purge, projects, tickets.launching_tickets).
"""
from bouzecode.web_v2.services.work import fleet, tickets, projects
from bouzecode.web_v2.services.sessions import store, purge
from bouzecode.web_v2.runtime import runner


class _FakeAgent:
    """Agent web tel que renvoyé par runner.list_agents (champs lus par _node)."""

    def __init__(self, agent_id: str, ticket_id: str = ""):
        self.agent_id = agent_id
        self.ticket_id = ticket_id
        self.session_path = ""
        self.pid = 0        # aucun process réel : l'agent n'est jamais « warm »
        self.ipc_dir = ""
        self.finished_at = ""
        self.returncode = None
        self.model = ""
        self.prompt = "prompt agent"
        self.parent = ""
        self.cwd = ""
        self.started_at = "2026-07-15T11:00:00"
        self.profile = ""
        self.run_kind = "work"


def _wire_tree(monkeypatch, agents, launching):
    """Isole _agent_tree_uncached : agents spawnés + tickets launching contrôlés."""
    monkeypatch.setattr(runner, "list_agents", lambda: agents)
    monkeypatch.setattr(runner, "refresh_agent_status", lambda a: a)
    monkeypatch.setattr(runner, "get_ipc_state", lambda a: {})
    monkeypatch.setattr(runner, "is_running", lambda a: True)
    monkeypatch.setattr(store, "list_agent_sessions", lambda: [])
    monkeypatch.setattr(purge, "load_deleted", lambda: set())
    monkeypatch.setattr(projects, "list_projects", lambda: [
        {"slug": "demo-app", "name": "Demo App", "path": "C:/repo"},
    ])
    monkeypatch.setattr(projects, "find", lambda slug: (
        {"slug": "demo-app", "name": "Demo App", "path": "C:/repo"} if slug == "demo-app" else None
    ))
    monkeypatch.setattr(projects, "project_for_cwd", lambda cwd, plist: None)
    monkeypatch.setattr(tickets, "launching_tickets", lambda: launching)


def test_launching_tickets_filters_only_launching(monkeypatch, tmp_path):
    """launching_tickets() parcourt tous les stores {slug}.json et ne renvoie
    QUE les tickets marqués launching (0 I/O agent)."""
    monkeypatch.setattr(tickets, "TICKETS_DIR", tmp_path)
    t_launch = tickets.create_ticket("demo-app", "Feature en lancement", "prompt A")
    t_idle = tickets.create_ticket("demo-app", "Ticket normal", "prompt B")
    tickets.set_launching("demo-app", t_launch)

    result = tickets.launching_tickets()

    ids = {tid for _, tk in result for tid in [tk["id"]]}
    assert t_launch["id"] in ids
    assert t_idle["id"] not in ids
    assert all(tk.get("launching") for _, tk in result)


def test_launching_ticket_without_agent_becomes_provisioning_node(monkeypatch):
    """Ticket launching SANS agent spawné → 1 node synthétique state=provisioning
    avec phase + key launching/<id>, injecté dans l'arbre."""
    ticket = {
        "id": "tick1234", "title": "Ma feature", "prompt": "corrige le bug",
        "created_at": "2026-07-15T11:05:00", "launching": True,
        "phase": "provisioning_worktree",
    }
    _wire_tree(monkeypatch, agents=[], launching=[("demo-app", ticket)])

    tree = fleet._agent_tree_uncached()
    nodes = tree["nodes"]

    assert len(nodes) == 1
    n = nodes[0]
    assert n["key"] == "launching/tick1234"
    assert n["ticket_id"] == "tick1234"
    assert n["state"] == "provisioning"
    assert n["phase"] == "provisioning_worktree"
    assert n["title"] == "Ma feature"
    assert n["project_slug"] == "demo-app"
    assert n["isolated"] is True


def test_launching_ticket_d_un_projet_inconnu_n_apparait_pas(monkeypatch):
    """Un drapeau `launching` resté sur un slug qui n'est pas (ou plus) un projet ouvert ne
    fabrique pas de conversation fantôme : il n'y a aucune page projet derrière pour l'ouvrir."""
    ticket = {
        "id": "fantome1", "title": "Vieux lancement", "prompt": "p",
        "created_at": "2026-07-15T11:05:00", "launching": True,
    }
    _wire_tree(monkeypatch, agents=[], launching=[("slug-inconnu", ticket)])

    assert fleet._agent_tree_uncached()["nodes"] == []


def test_launching_node_deduped_when_agent_spawned(monkeypatch):
    """Un agent porte déjà ce ticket_id (spawn effectué) → PAS de doublon :
    le vrai node agent prime, aucun node launching synthétique n'est ajouté."""
    ticket = {
        "id": "tick1234", "title": "Ma feature", "prompt": "corrige le bug",
        "created_at": "2026-07-15T11:05:00", "launching": True,
        "phase": "spawning",
    }
    agent = _FakeAgent("ag-real", ticket_id="tick1234")
    _wire_tree(monkeypatch, agents=[agent], launching=[("demo-app", ticket)])

    tree = fleet._agent_tree_uncached()
    nodes = tree["nodes"]

    keys = {n["key"] for n in nodes}
    assert "agent/ag-real" in keys
    assert "launching/tick1234" not in keys
    assert len(nodes) == 1
