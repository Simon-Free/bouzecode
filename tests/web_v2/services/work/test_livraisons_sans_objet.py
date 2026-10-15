"""Une carte « livraison à relire » sur une branche qui n'existe plus est purgée (classée, tracée).

Cas réel (essai du 2026-09-24, ~/bouzecode-essai) : trois cartes restaient « pending » sur les
tickets 4016d313, 2a3bb953 et c7d5ded1 — tickets archivés, worktrees fauchés, branches
`agent/<id>` supprimées. L'ingest sautait les tickets archivés AVANT de regarder leurs cartes :
plus rien ne pouvait les classer, et chacune comptait comme un point ouvert de sa tâche.

Vrai dépôt git temporaire, vraie base SQLite isolée : aucun mock.
"""
from __future__ import annotations

import pytest

from bouzecode.web_v2.services.work import decision_ingest, decisions, tickets
from tests.git_modeles import git as _git
from tests.git_modeles import livraison_non_integree


@pytest.fixture
def repo(tmp_path, depot_modele):
    return depot_modele(tmp_path / "repo", livraison_non_integree, "main", "agent/4016d313")


def _seed(repo, tmp_path, **extra):
    ticket = {"id": "4016d313", "title": "Scrapper les énigmes", "done": True,
              "worktree": {"repo_root": str(repo), "base": "main", "branch": "agent/4016d313",
                           "worktree": str(tmp_path / "wt" / "4016d313"),
                           "state": "provisioned"}, **extra}
    tickets.update_ticket("portail-enigmes", ticket)
    return ticket


def _cartes():
    return [row for row in decisions.open_decisions()
            if row["situation"] == decision_ingest.SITUATION_UNMERGED]


def test_ticket_archive_dont_la_branche_a_disparu_purge_sa_carte(repo, tmp_path):
    ticket = _seed(repo, tmp_path)
    decision_ingest.ingest()
    [carte] = _cartes()

    #  Ce qu'a fait le parc réel : ticket archivé, worktree fauché, branche supprimée.
    tickets.archive_ticket("portail-enigmes", ticket["id"])
    tickets.poser("portail-enigmes", ticket,  # lot L2 : fauché = `worktree.retire_at`
                  worktree={**ticket["worktree"], "retire_at": "2026-09-24T10:00:00"})
    _git(repo, "branch", "-D", "agent/4016d313")
    compte = decision_ingest.ingest()

    assert _cartes() == []
    assert compte["moot"] == 1
    relue = decisions.get(carte["id"])
    assert relue["delivery"] == "moot"
    assert "agent/4016d313" in relue["delivery_error"]
    assert "n'existe" in relue["delivery_error"]


def test_ticket_archive_dont_la_branche_existe_encore_garde_sa_carte(repo, tmp_path):
    """Des commits jamais intégrés sur une branche vivante restent une décision à prendre,
    même si la conversation a été rangée."""
    ticket = _seed(repo, tmp_path)
    decision_ingest.ingest()
    tickets.archive_ticket("portail-enigmes", ticket["id"])

    decision_ingest.ingest()

    assert len(_cartes()) == 1


def test_depot_introuvable_ne_purge_rien(repo, tmp_path):
    """Objet invérifiable (dépôt déplacé, disque débranché) : on ne touche à rien."""
    ticket = _seed(repo, tmp_path)
    decision_ingest.ingest()
    tickets.archive_ticket("portail-enigmes", ticket["id"])
    tickets.poser("portail-enigmes", ticket,
                  worktree={**ticket["worktree"], "repo_root": str(tmp_path / "ailleurs")})

    decision_ingest.ingest()

    assert len(_cartes()) == 1
