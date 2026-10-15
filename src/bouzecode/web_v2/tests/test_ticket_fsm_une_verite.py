# [desc] Critère 2 (L2) : pour CHAQUE état de la machine, la fiche, la liste, /api/agents/tree, /api/lignes, /api/inbox et /api/agents/activity disent le même `state` et le même libellé — tous lisent `ticket.state`. [/desc]
from __future__ import annotations

import json
from datetime import datetime

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.runtime.runner import agent_fiche, agent_registre
from bouzecode.web_v2.services.work import fleet, micros, projects, taches_vue, tickets
from bouzecode.web_v2.services.work.fsm import etats

SLUG = "p"
#: state → code de raison posé (un état peut se lire différemment selon sa raison).
RAISON = {etats.LAUNCH_FAILED: "lancement_echoue", etats.STOPPED: "crashed",
          etats.IDLE_NO_DELIVERY: "max_turns_exceeded", etats.CONFLICT: "conflit",
          etats.CLOSED: "accepte", etats.ABANDONED: "abandonne"}
SANS_RUN = (etats.CREATED, etats.PROVISIONING, etats.LAUNCH_FAILED)
#: États dont la tâche du Bureau attend un geste humain : ils ont une carte dans l'inbox.
AVEC_CARTE = (etats.LAUNCH_FAILED, etats.AWAITING_INPUT, etats.DELIVERED,
              etats.IDLE_NO_DELIVERY, etats.STOPPED)


def _maintenant() -> str:
    return datetime.now().isoformat(timespec="seconds")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    chemin = tmp_path / "projects.json"
    monkeypatch.setattr(projects, "PROJECTS_PATH", chemin)
    chemin.write_text(json.dumps([{"slug": SLUG, "name": "p", "path": str(tmp_path)}]),
                      encoding="utf-8")
    monkeypatch.setattr(taches_vue, "CACHE_TTL", 0)
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _fiche_d_agent(agent_id: str, ticket_id: str, cwd: str) -> None:
    """Un agent fini, tel que le runner l'écrit : l'arbre en fait un nœud."""
    parc = agent_fiche.AGENTS_DIR
    (parc / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id, "prompt": "Corrige le calcul des remises", "model": "m",
        "cwd": cwd, "pid": None, "started_at": _maintenant(), "returncode": 0,
        "finished_at": _maintenant(), "session_path": str(parc / f"{agent_id}.session.json"),
        "stdout_path": str(parc / f"{agent_id}.out.log"), "ipc_dir": "", "parent": "",
        "ticket_slug": SLUG, "ticket_id": ticket_id}), encoding="utf-8")
    agent_fiche._list_agents_cache.clear()
    agent_registre._agent_file_cache.clear()


def _semer(state: str, cwd: str) -> dict:
    """Un ticket DANS l'état voulu (ensemencé : l'état passé fait foi), relié à une tâche."""
    ident = f"t{etats.ETATS.index(state):07d}"
    code = RAISON.get(state)
    run = {"agent_id": f"ag{ident}", "kind": "work", "model": "m", "started_at": _maintenant(),
           "state": "running" if state in (etats.RUNNING, etats.AWAITING_INPUT) else "ended"}
    ticket = {"id": ident, "title": f"Ticket {state}", "prompt": "Corrige le calcul des remises",
              "created_at": _maintenant(), "comments": [], "state": state,
              "state_reason": {"code": code, "message": "", "at": _maintenant()} if code else None,
              "runs": [] if state in SANS_RUN else [run]}
    tickets._save_unlocked(SLUG, [ticket])
    if state not in SANS_RUN:
        _fiche_d_agent(run["agent_id"], ident, cwd)
    macro = micros.ensure_macro("Remises")
    micro = micros.create_micro(titre=f"Tâche {state}", macro_id=macro["id"], projet_slug=SLUG)
    micros.lier_ticket(micro["id"], slug=SLUG, ticket_id=ident)
    micros.marquer_etat(micro["id"], "lancee")
    return tickets.get_ticket(SLUG, ident)


def _lignes(client, url: str) -> list[dict]:
    vue = client.get(url).get_json()
    return [l for c in vue["chantiers"] for l in c["lignes"]] + vue["non_rattachees"]


def _vu_par_le_bureau(client, ident: str) -> set[tuple]:
    """Ce que /api/lignes dit du ticket : liste allégée (dernier passage) et liste complète
    (tickets de la ligne, et leurs passages)."""
    vus = set()
    for ligne in _lignes(client, "/api/lignes"):
        vus |= {(p["ticket_state"], p["libelle_ticket"]) for p in ligne.get("passages") or []
                if p.get("ticket_id") == ident}
    for ligne in _lignes(client, "/api/lignes?complet=1"):
        vus |= {(t["state"], t["libelle_statut"]) for t in ligne.get("tickets") or []
                if t.get("ticket_id") == ident}
        vus |= {(p["ticket_state"], p["libelle_ticket"]) for p in ligne.get("passages") or []
                if p.get("ticket_id") == ident}
    return vus


@pytest.mark.parametrize("state", etats.ETATS)
def test_chaque_surface_dit_le_meme_etat(client, tmp_path, state):
    ticket = _semer(state, str(tmp_path))
    ident = ticket["id"]
    fiche = client.get(f"/api/projects/{SLUG}/tickets/{ident}").get_json()
    assert fiche["state"] == state
    libelle = fiche["libelle_statut"]
    assert libelle

    liste = client.get(f"/api/projects/{SLUG}/tickets").get_json()["tickets"]
    assert [(t["state"], t["libelle_statut"]) for t in liste if t["id"] == ident] == [
        (state, libelle)]

    fleet.clear_tree_cache()
    noeuds = [n for n in client.get("/api/agents/tree").get_json()["nodes"]
              if n.get("ticket_id") == ident]
    if state != etats.CREATED:  # un ticket jamais lancé n'a aucun nœud : rien à montrer
        assert noeuds, f"aucun nœud pour un ticket {state}"
    assert {(n["ticket_state"], n["libelle_ticket"]) for n in noeuds} <= {(state, libelle)}

    assert _vu_par_le_bureau(client, ident) == {(state, libelle)}

    taches_vue.invalider()
    cartes = [c for c in client.get("/api/inbox").get_json()["items"]
              if c.get("ticket_id") == ident or c.get("ticket_state") and
              (c.get("tache") or {}).get("titre") == f"Tâche {state}"]
    if state in AVEC_CARTE:
        assert cartes, f"aucune carte pour un ticket {state}"
    assert {(c["ticket_state"], c["libelle_ticket"]) for c in cartes} <= {(state, libelle)}

    actifs = [a for a in client.get("/api/agents/activity").get_json()["agents"]
              if a.get("ticket_id") == ident]
    if state == etats.PROVISIONING:  # le lancement en cours a sa ligne de surveillance
        assert actifs, "aucune ligne d'activité pour un ticket en préparation"
    assert {(a["ticket_state"], a["libelle_ticket"]) for a in actifs} <= {(state, libelle)}
