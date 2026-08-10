"""Défaut de typologie côté serveur (CHANTIER 2).

Sur un PROJET DE CODE (dépôt git) sans typology explicite, le serveur applique le
profil codeur `coder` — mais UNIQUEMENT pour un lancement MANAGÉ (le ticket porte le
`parent` du manager qui l'a dispatché). Un ticket créé À LA MAIN depuis l'UI, sans
typology ni parent, reste un agent NU, comme en TUI : le défaut codeur lui était
appliqué par accident, les routes appelant resolve_profile() sans passer `managed=`.
Une typology explicite (ex: manager) est TOUJOURS respectée, et un projet non-code
ne reçoit aucun défaut.

Tests user-centric : VRAIS endpoints Flask (POST tickets + /launch), vraie fonction
publique resolve_profile, vrai `git init` en dossier temp. Aucun unittest.mock.
"""
import subprocess

import pytest

from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work import dispatch
from bouzecode.web_v2.routes.work import tickets as tickets_routes


def _git_init(path):
    """Fait de `path` un vrai dépôt git (repos.repo_root() y répond vrai)."""
    subprocess.run(["git", "init", "-q"], cwd=str(path), check=True)


# ---------------------------------------------------------------------------
# 1) resolve_profile : le cœur de la règle, testé directement (fonction publique)
# ---------------------------------------------------------------------------

def test_resolve_profile_repo_git_sans_typology_defaut_coder(monkeypatch, tmp_path):
    _git_init(tmp_path)
    # Aucune typology → get_typology n'est même pas consulté (name vide).
    assert dispatch.resolve_profile("", str(tmp_path)) == "coder"


def test_resolve_profile_repo_git_typology_default_aussi_coder(monkeypatch, tmp_path):
    _git_init(tmp_path)
    # typology "default" == profile vide → traité comme absence → défaut codeur.
    monkeypatch.setattr(dispatch, "get_typology",
                        lambda name, path: {"profile": "", "default_model": ""})
    assert dispatch.resolve_profile("default", str(tmp_path)) == "coder"


def test_resolve_profile_typology_explicite_manager_conservee(monkeypatch, tmp_path):
    _git_init(tmp_path)
    # manager a un profil non vide → RESPECTÉ tel quel, aucun défaut appliqué.
    monkeypatch.setattr(dispatch, "get_typology",
                        lambda name, path: {"profile": "manager", "default_model": ""})
    assert dispatch.resolve_profile("manager", str(tmp_path)) == "manager"


def test_resolve_profile_projet_non_code_sans_typology_reste_vide(monkeypatch, tmp_path):
    # tmp_path N'EST PAS un dépôt git → pas de défaut, agent standard (profile vide).
    assert dispatch.resolve_profile("", str(tmp_path)) == ""


# ---------------------------------------------------------------------------
# 2) VRAIS endpoints Flask : création de ticket + /launch
# ---------------------------------------------------------------------------

@pytest.fixture()
def code_project(monkeypatch, tmp_path):
    """Projet de CODE (git init réel) + store tickets temp + pas d'isolation ni spawn."""
    _git_init(tmp_path)
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path / "tickets")
    project = {"slug": "p", "name": "Projet", "path": str(tmp_path)}
    monkeypatch.setattr(
        tickets_routes, "_project_or_404",
        lambda slug: (project, None) if slug == "p" else (None, ({"error": "nf"}, 404)),
    )
    monkeypatch.setattr(
        tickets_routes, "_ticket_or_404",
        lambda slug, tid: (tickets_svc.get_ticket("p", tid), None),
    )
    # Pas d'isolation réelle (worktree/venv) ni de décision réseau.
    monkeypatch.setattr(tickets_routes.dispatch, "resolve_isolation",
                        lambda path, requested, **kw: (dispatch.SHARED, "test", ""))
    return project


@pytest.fixture()
def client(code_project):
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _capture_launch(monkeypatch):
    """Fake _launch : capture le `profile` reçu, sans git ni spawn."""
    seen = {}

    def fake_launch(slug, ticket, project_path, profile, model,
                    isolation=dispatch.SHARED, parent="", resume_branch=""):
        seen["profile"] = profile
        tickets_svc.add_run(slug, ticket, "agent-" + ticket["id"], "work", model,
                            typology=ticket.get("typology", ""))

    monkeypatch.setattr(tickets_routes.dispatch, "_launch", fake_launch)
    return seen


def test_creation_ticket_manuel_sans_typology_reste_nu(client, monkeypatch):
    """Ticket créé À LA MAIN (aucun parent) et sans typology → agent NU, pas `coder`."""
    seen = _capture_launch(monkeypatch)
    # defer=False → chemin synchrone déterministe : _launch reçoit le profile résolu.
    resp = client.post("/api/projects/p/tickets",
                       json={"title": "T", "prompt": "fais un truc", "defer": False})
    assert resp.status_code == 200
    assert seen["profile"] == ""


def test_creation_ticket_dispatche_par_un_manager_applique_coder(client, monkeypatch):
    """Même ticket, mais dispatché PAR UN MANAGER (parent = agent_id) → défaut `coder`."""
    seen = _capture_launch(monkeypatch)
    resp = client.post("/api/projects/p/tickets",
                       json={"title": "T", "prompt": "fais un truc",
                             "parent": "agent-manager-42", "defer": False})
    assert resp.status_code == 200
    assert seen["profile"] == "coder"


def test_creation_ticket_parent_manuel_sentinelle_reste_nu(client, monkeypatch):
    """Le sentinelle `dispatcher:manual` n'est PAS un manager : agent NU."""
    seen = _capture_launch(monkeypatch)
    resp = client.post("/api/projects/p/tickets",
                       json={"title": "T", "prompt": "fais un truc",
                             "parent": "dispatcher:manual", "defer": False})
    assert resp.status_code == 200
    assert seen["profile"] == ""


def test_creation_ticket_typology_explicite_manager_conservee(client, monkeypatch):
    seen = _capture_launch(monkeypatch)
    monkeypatch.setattr(dispatch, "get_typology",
                        lambda name, path: {"profile": "manager", "default_model": ""})
    resp = client.post("/api/projects/p/tickets",
                       json={"title": "T", "prompt": "orchestre", "typology": "manager",
                             "defer": False})
    assert resp.status_code == 200
    # Typology explicite respectée : PAS de défaut coder appliqué.
    assert seen["profile"] == "manager"


def _capture_create_agent(monkeypatch):
    """Fake runner.create_agent : capture le `profile` reçu, sans spawn de process."""
    captured = {}

    def fake_create_agent(prompt, model, cwd, profile="", **kwargs):
        captured["profile"] = profile

        class _Agent:
            agent_id = "a1"
        return _Agent()

    monkeypatch.setattr(tickets_routes.runner, "create_agent", fake_create_agent)
    # /launch passe par api_sanity ; on neutralise le garde-fou dans ce test.
    from bouzecode.web_v2 import api_sanity
    monkeypatch.setattr(api_sanity, "require_api_sanity", lambda: None)
    return captured


def test_launch_ticket_manuel_sans_typology_reste_nu(client, monkeypatch):
    """Relance d'un ticket sans parent ni typology → agent NU, pas `coder`."""
    captured = _capture_create_agent(monkeypatch)
    t = tickets_svc.create_ticket("p", "T", "prompt de launch")

    resp = client.post(f"/api/tickets/p/{t['id']}/launch", json={})
    assert resp.status_code == 200
    assert captured["profile"] == ""


def test_launch_ticket_dun_manager_applique_coder(client, monkeypatch):
    """Relance d'un ticket dispatché par un manager → le défaut `coder` s'applique,
    même si le payload de relance ne redit ni typology ni parent."""
    captured = _capture_create_agent(monkeypatch)
    t = tickets_svc.create_ticket("p", "T", "prompt de launch")
    t["parent"] = "agent-manager-42"
    tickets_svc.update_ticket("p", t)

    resp = client.post(f"/api/tickets/p/{t['id']}/launch", json={})
    assert resp.status_code == 200
    assert captured["profile"] == "coder"


def test_launch_typology_explicite_manager_conservee(client, monkeypatch):
    captured = _capture_create_agent(monkeypatch)
    monkeypatch.setattr(dispatch, "get_typology",
                        lambda name, path: {"profile": "manager", "default_model": ""})

    t = tickets_svc.create_ticket("p", "T", "prompt")
    resp = client.post(f"/api/tickets/p/{t['id']}/launch",
                       json={"typology": "manager"})
    assert resp.status_code == 200
    assert captured["profile"] == "manager"


def test_relance_dun_ticket_manager_ne_retombe_pas_sur_coder(client, monkeypatch):
    """La typology PORTÉE PAR LE TICKET survit à une relance sans payload : un ticket
    `manager` relancé reste `manager` et ne se voit pas attribuer `coder`."""
    captured = _capture_create_agent(monkeypatch)
    monkeypatch.setattr(dispatch, "get_typology",
                        lambda name, path: {"profile": "manager", "default_model": ""})

    t = tickets_svc.create_ticket("p", "T", "orchestre")
    t["typology"] = "manager"
    t["parent"] = "agent-manager-42"
    tickets_svc.update_ticket("p", t)

    resp = client.post(f"/api/tickets/p/{t['id']}/launch", json={})
    assert resp.status_code == 200
    assert captured["profile"] == "manager"
