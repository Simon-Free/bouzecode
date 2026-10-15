# [desc] Archivage sans destruction et nettoyage disque gardé (run vivant, travail non récolté) : un worktree n'est jamais retiré sous un agent ni sale. [/desc]
"""Spec ticketing §5.5, principe B9, constats C4, C5b, C15 — via les VRAIES routes Flask.

* `POST …/archive` masquait le ticket ET retirait son worktree, même sous un agent vivant
  (la garde lisait un état de run périmé, C4). Il ne retire plus rien.
* `POST …/cleanup` est le geste disque : refusé en 409 `run_vivant` (vrai process vérifié à
  l'instant) ou `travail_non_recolte` (arbre resté sale après la récolte, C15) ; sinon 202,
  worktree retiré, branche GARDÉE.
* `POST …/unarchive` après disparition du worktree laisse un état cohérent (C5b).
Vrai git, vrais fichiers d'agent (le PID du process de test pour un agent vivant), aucun mock."""
from __future__ import annotations

import json
import os
from pathlib import Path

from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import nettoyage, worktrees
from bouzecode.web_v2.services.work import tickets as tickets_svc

from delivery_repo import (  # noqa: F401 — fixtures pytest
    CODEUR, SLUG, agents_dir, block_git_index, client, delivered_ticket, develop_repo,
    git_out, project,
)


def _agent_vivant(agents_dir: Path, cwd: str) -> None:
    """Fiche d'un codeur dont le process TOURNE : le PID est celui du process de test."""
    (agents_dir / f"{CODEUR}.json").write_text(json.dumps({
        "agent_id": CODEUR, "prompt": "corrige", "model": "opus", "cwd": cwd,
        "pid": os.getpid(), "started_at": "2026-10-05T10:00:00",
        "session_path": str(agents_dir / f"{CODEUR}.session.json"),
    }), encoding="utf-8")
    store.invalidate_status(CODEUR)
    agent_fiche._list_agents_cache.clear()


def test_archiver_ne_detruit_rien_meme_sous_un_agent_vivant(client, project, agents_dir):
    ticket = delivered_ticket(project, "archivé en plein travail", produced="encours.py")
    _agent_vivant(agents_dir, ticket["worktree"]["worktree"])

    resp = client.put(f"/api/projects/{SLUG}/tickets/{ticket['id']}/archived", json={"archived": True})

    assert resp.status_code == 200 and resp.get_json()["archived"] is True
    assert (Path(ticket["worktree"]["worktree"]) / "encours.py").is_file()


def test_cleanup_refuse_sous_un_run_vivant(client, project, agents_dir):
    ticket = delivered_ticket(project, "agent vivant", produced="encours.py")
    _agent_vivant(agents_dir, ticket["worktree"]["worktree"])

    resp = client.post(f"/api/projects/{SLUG}/tickets/{ticket['id']}/cleanup", json={"defer": False})

    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "run_vivant"
    assert (Path(ticket["worktree"]["worktree"]) / "encours.py").is_file()
    branch = ticket["worktree"]["branch"]
    assert "encours.py" not in git_out(project, "ls-tree", "--name-only", branch)  # rien commité


def test_cleanup_refuse_un_arbre_que_la_recolte_laisse_sale(client, project):
    ticket = delivered_ticket(project, "index verrouillé", produced="perdu.py")
    block_git_index(ticket["worktree"]["worktree"])

    resp = client.post(f"/api/projects/{SLUG}/tickets/{ticket['id']}/cleanup", json={"defer": False})

    assert resp.status_code == 409
    erreur = resp.get_json()["error"]
    assert erreur["code"] == "travail_non_recolte" and erreur["details"]["files"] == ["perdu.py"]
    assert (Path(ticket["worktree"]["worktree"]) / "perdu.py").is_file()  # worktree INTACT


def test_cleanup_recolte_retire_le_worktree_et_garde_la_branche(client, project):
    ticket = delivered_ticket(project, "à ranger", produced="garde.py")
    branch = ticket["worktree"]["branch"]

    resp = client.post(f"/api/projects/{SLUG}/tickets/{ticket['id']}/cleanup", json={"defer": False})

    assert resp.status_code == 202 and resp.get_json()["state"] == "removed"
    assert not Path(ticket["worktree"]["worktree"]).exists()
    assert "garde.py" in git_out(project, "ls-tree", "--name-only", branch)
    again = client.post(f"/api/projects/{SLUG}/tickets/{ticket['id']}/cleanup", json={"defer": False})
    assert again.status_code == 202 and again.get_json()["state"] == "rien_a_nettoyer"


def test_un_ticket_nettoye_reste_integrable_depuis_sa_branche(client, project):
    """C5b : un worktree disparu ne vaut jamais « rien à intégrer »."""
    ticket = delivered_ticket(project, "nettoyé puis intégré", produced="tardif.py")
    client.post(f"/api/projects/{SLUG}/tickets/{ticket['id']}/cleanup", json={"defer": False})

    resp = client.post(f"/api/projects/{SLUG}/tickets/{ticket['id']}/integrate",
                       json={"wait": True})

    assert resp.status_code == 202, resp.get_json()
    assert tickets_svc.get_ticket(SLUG, ticket["id"])["state"] == "closed"
    assert "tardif.py" in git_out(project, "ls-tree", "--name-only", "develop")


def test_desarchiver_constate_un_worktree_disparu(client, project):
    ticket = delivered_ticket(project, "archivé, worktree effacé à la main", produced="x.py")
    client.put(f"/api/projects/{SLUG}/tickets/{ticket['id']}/archived", json={"archived": True})
    worktrees.harvest(ticket["worktree"], "sauvé avant effacement")
    worktrees.reap(ticket["worktree"], delete_branch=False)  # disparition hors du serveur

    client.put(f"/api/projects/{SLUG}/tickets/{ticket['id']}/archived", json={"archived": False})

    stored = tickets_svc.get_ticket(SLUG, ticket["id"])
    assert stored["worktree"]["retire_at"] and not stored.get("archived")
    resp = client.post(f"/api/projects/{SLUG}/tickets/{ticket['id']}/integrate",
                       json={"wait": True})
    assert resp.status_code == 202
    assert tickets_svc.get_ticket(SLUG, ticket["id"])["state"] == "closed"


def test_supprimer_un_projet_epargne_le_ticket_dont_un_run_vit(project, agents_dir):
    vivant = delivered_ticket(project, "vivant", produced="a.py")
    _agent_vivant(agents_dir, vivant["worktree"]["worktree"])
    assert nettoyage.nettoyer_le_projet(SLUG) == []
    assert Path(vivant["worktree"]["worktree"]).is_dir()
