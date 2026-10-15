# [desc] Garde « lecture pure » (spec ticketing B1, critère 1) : 10 appels des GET tickets/agents ne changent ni le store SQLite, ni les branches/commits git, ni le worktree. [/desc]
"""Un GET n'a jamais d'effet de bord (constat C1 : la liste des tickets commitait du WIP,
mergeait, fauchait des worktrees et réveillait des managers).

Décor réel : un dépôt git, un worktree d'agent avec du travail NON COMMITÉ, un ticket livré
dont l'agent est mort proprement, un second ticket dont l'agent a disparu sans clôture (ce que
le watchdog classerait « planté »). On photographie la base, les branches, le journal et
l'état du worktree, on appelle chaque GET dix fois, et rien ne doit avoir bougé.
"""
from __future__ import annotations

import sqlite3

from bouzecode.web_v2.services.work import _persistence
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.tests.delivery_repo import (  # noqa: F401 — fixtures
    CODEUR, SLUG, agents_dir, client, delivered_ticket, develop_repo, finished_agent, git_out,
    project,
)

AGENT_DISPARU = "d15a99e4d000"


def _photo_de_la_base() -> dict:
    """Le contenu des tables NON VIDES : une lecture peut créer le schéma (vide) des tables
    du Bureau à leur première ouverture, ce qui n'est pas une écriture de données."""
    with sqlite3.connect(f"file:{_persistence._db_path()}?mode=ro", uri=True) as base:
        tables = [nom for (nom,) in base.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        lignes = {table: base.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                  for table in tables}
    return {table: contenu for table, contenu in lignes.items() if contenu}


def _photo_git(repo, worktree: str) -> tuple:
    return (git_out(repo, "branch", "-a", "-v", "--no-abbrev"),
            git_out(repo, "log", "--all", "--format=%H %s"),
            git_out(repo, "worktree", "list", "--porcelain"),
            git_out(worktree, "status", "--porcelain"))


def _gets(ticket_id: str) -> list[str]:
    return [f"/api/projects/{SLUG}/tickets", f"/api/projects/{SLUG}/tickets?include_archived=1",
            f"/api/projects/{SLUG}/tickets/{ticket_id}", "/api/projects", "/api/agents/tree",
            f"/api/agents/{CODEUR}/children", "/api/agents/activity",
            f"/api/agents?project={SLUG}", "/api/agents?state=awaiting_input"]


def test_les_get_tickets_et_agents_ne_changent_ni_le_store_ni_git(project, agents_dir, client):
    livre = delivered_ticket(project, "livré, WIP non commité")
    finished_agent(agents_dir, livre["worktree"]["worktree"])
    disparu = tickets_svc.create_ticket(SLUG, "agent disparu", "travaille")
    tickets_svc.add_run(SLUG, disparu, AGENT_DISPARU, "work", "", typology="coder")
    worktree = livre["worktree"]["worktree"]

    base_avant, git_avant = _photo_de_la_base(), _photo_git(project, worktree)
    assert git_avant[3], "le worktree doit porter du travail non commité"
    for _ in range(10):
        for url in _gets(livre["id"]):
            reponse = client.get(url)
            assert reponse.status_code == 200, (url, reponse.get_data(as_text=True)[:300])

    assert _photo_de_la_base() == base_avant
    assert _photo_git(project, worktree) == git_avant
