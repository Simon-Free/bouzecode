"""POST /api/projects/<slug>/tickets : lancement asynchrone (defer par défaut).

Tests user-centric via le VRAI endpoint Flask (client de test), store tickets sur un
dossier temp réel (pas de mock du service), et le travail lourd (worktree+spawn) est
remplacé par un fake _launch/_launch_bg synchronisé par threading.Event. Aucun mock
unittest, aucun LLM, aucun git.
"""
import threading

import pytest

from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work import dispatch
from bouzecode.web_v2.services.work import _persistence
from bouzecode.web_v2.routes.work import tickets as tickets_routes


@pytest.fixture()
def wired(monkeypatch, tmp_path):
    """Store tickets réel sur temp + projet factice + pas d'isolation ni typology réseau."""
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path / "tickets")
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path / "tickets")
    project = {"slug": "p", "name": "Projet", "path": str(tmp_path)}
    monkeypatch.setattr(
        tickets_routes, "_project_or_404",
        lambda slug: (project, None) if slug == "p" else (None, ({"error": "nf"}, 404)),
    )
    monkeypatch.setattr(
        "bouzecode.web_v2.services.typologies.get_typology",
        lambda name, path: {"profile": "", "default_model": ""},
    )
    monkeypatch.setattr(dispatch, "resolve_isolation",
                        lambda path, requested, needs_worktree=False: ("shared", "test", ""))
    return project


@pytest.fixture()
def client(wired):
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _launched_recorder(monkeypatch):
    """Fake _launch : enregistre l'appel et signale un Event, sans git ni spawn."""
    launched = threading.Event()
    seen: list[str] = []

    def fake_launch(slug, ticket, project_path, profile, model, isolation="shared",
                    parent="", resume_branch="", work_branch=""):
        seen.append(ticket["id"])
        # Simule le vrai _launch : enregistre un run (retire l'état launching).
        tickets_svc.add_run(slug, ticket, "agent-" + ticket["id"], "work", model,
                            typology=ticket.get("typology", ""))
        launched.set()

    monkeypatch.setattr(dispatch, "_launch", fake_launch)
    return launched, seen


def test_post_repond_vite_avec_launching_puis_run_en_fond(client, monkeypatch):
    launched, seen = _launched_recorder(monkeypatch)

    resp = client.post("/api/projects/p/tickets",
                       json={"title": "T", "prompt": "fais un truc", "typology": "default"})

    assert resp.status_code == 200
    body = resp.get_json()
    tid = body["id"]
    # Réponse immédiate : le ticket est créé et marqué 'launching' AVANT tout run.
    assert tid
    assert body.get("launching") is True

    # Le lancement lourd part bien en fond, sur CE ticket.
    assert launched.wait(3)
    assert seen == [tid]


def test_trois_post_en_rafale_trois_tickets_trois_runs(client, monkeypatch):
    launched, seen = _launched_recorder(monkeypatch)

    ids = []
    for i in range(3):
        r = client.post("/api/projects/p/tickets",
                        json={"title": f"T{i}", "prompt": f"tache {i}", "typology": "default"})
        assert r.status_code == 200
        ids.append(r.get_json()["id"])

    assert len(set(ids)) == 3
    # Les 3 lancements en fond aboutissent (aucun blocage mutuel).
    for _ in range(30):
        if len(seen) == 3:
            break
        threading.Event().wait(0.1)
    assert sorted(seen) == sorted(ids)
    # Le lancement en fond persiste le run APRÈS avoir signalé `seen` : sur le store
    # SQLite (connexion thread-local + WAL) add_run est plus lent que l'ancien write
    # JSON synchrone, donc on attend que les 3 runs soient RÉELLEMENT persistés avant
    # d'asserter — même pattern d'attente que test_echec.
    for _ in range(30):
        if all(tickets_svc.get_ticket("p", tid)["runs"] for tid in ids):
            break
        threading.Event().wait(0.1)
    for tid in ids:
        t = tickets_svc.get_ticket("p", tid)
        assert t["runs"], f"ticket {tid} sans run"
        assert not t.get("launching"), f"ticket {tid} encore launching"


def test_defer_false_chemin_synchrone_run_present_dans_reponse(client, monkeypatch):
    _launched_recorder(monkeypatch)

    resp = client.post("/api/projects/p/tickets",
                       json={"title": "T", "prompt": "sync", "typology": "default",
                             "defer": False})

    assert resp.status_code == 200
    body = resp.get_json()
    # Synchrone : le run est déjà là dans la réponse, pas d'état launching résiduel.
    assert body["runs"], "run absent en mode synchrone"
    assert not body.get("launching")


def test_echec_lancement_en_fond_laisse_une_trace_visible(client, monkeypatch):
    boom_done = threading.Event()

    def boom(*a, **k):
        try:
            raise RuntimeError("provider env manquant")
        finally:
            boom_done.set()

    monkeypatch.setattr(dispatch, "_launch", boom)

    resp = client.post("/api/projects/p/tickets",
                       json={"title": "T", "prompt": "va planter", "typology": "default"})
    assert resp.status_code == 200
    tid = resp.get_json()["id"]

    assert boom_done.wait(3)
    # Laisse le thread finir sa gestion d'erreur (pop launching + add_comment).
    for _ in range(30):
        t = tickets_svc.get_ticket("p", tid)
        if t.get("comments") and not t.get("launching"):
            break
        threading.Event().wait(0.1)
    t = tickets_svc.get_ticket("p", tid)
    assert not t.get("launching"), "launching pas retiré après échec"
    assert t.get("comments"), "aucun commentaire d'échec visible"
    assert any("chou" in c["text"].lower() or "échou" in c["text"].lower()
               or "⚠" in c["text"] for c in t["comments"])


def test_derive_status_launching_est_en_cours(monkeypatch, tmp_path):
    t = tickets_svc.create_ticket("p", "T", "prompt")
    tickets_svc.set_launching("p", t)
    fresh = tickets_svc.get_ticket("p", t["id"])
    assert fresh.get("launching") is True
    assert tickets_svc.derive_status(fresh) == "en cours"
    assert tickets_svc.ticket_summary(fresh).get("launching") is True
