"""Une tâche dont il ne reste RIEN à faire se clôt toute seule — c'est le cœur du lot L2.

Avant : `derive_status` rendait « à relire » pour toute livraison terminée, et « à relire » n'est
jamais « terminé » ⇒ AUCUNE tâche ne se clôturait, le board grossissait indéfiniment (34 tickets
du parc réel sans le moindre acte restant). Ici on prouve la chaîne complète, sans mock :
vrai dépôt git, vraie base SQLite (isolée par la fixture autouse du conftest racine).

Sens de lecture : on part TOUJOURS d'un ticket qui porte du travail non intégré, donc d'une tâche
réellement ouverte, puis on lui retire son acte restant. Partir d'un ticket déjà fini ne prouverait
rien — `migrate_tickets_into_tasks` ne l'enrôlerait même pas.

RÉGIME À DEUX TEMPS, à ne pas prendre pour un bug : dans un tour de watchdog, la réconciliation
passe AVANT l'ingestion (seul endroit git du Bureau). Au premier tour, le ticket ne porte pas encore
`unmerged_commits`, donc il paraît terminé et n'est pas enrôlé ; l'ingestion le mesure et l'inscrit
sur le ticket ; c'est le tour SUIVANT qui crée la tâche. D'où les `_ticks(2)` : le watchdog tourne
toutes les 8 secondes, deux tours c'est 16 secondes, pas une anomalie.
"""

from __future__ import annotations

import pytest

from bouzecode.web_v2.services.work import (
    decision_ingest, decisions, task_migration, tasks,
)
from bouzecode.web_v2.tests.aides_tickets import semer
from tests.git_modeles import git as _git
from tests.git_modeles import livraison_non_integree


@pytest.fixture
def repo(tmp_path, depot_modele):
    """`develop` (1 commit) et `agent/t1` (1 commit de plus) : la situation exacte des 22 tickets
    du parc réel dont la branche porte du travail jamais intégré."""
    return depot_modele(tmp_path / "repo", livraison_non_integree, "develop", "agent/t1")


def _seed(slug, ticket_id, repo):
    """Un ticket LIVRÉ (lot L2 : `state=delivered`) dont la branche n'est pas intégrée."""
    return semer(slug, ticket_id, "delivered", title="Corriger le poller",
                 worktree={"repo_root": str(repo), "base": "develop", "branch": "agent/t1"})


def _tick():
    """Un tour de watchdog, dans l'ordre réel de `wake._reconcile_bureau_tasks`."""
    task_migration.reconcile_tasks_with_tickets()
    return decision_ingest.ingest()


def _ticks(n):
    for _ in range(n):
        report = _tick()
    return report


def _task_id(slug, ticket_id):
    for link in tasks.all_links():
        if link["slug"] == slug and link["ticket_id"] == ticket_id:
            return link["task_id"]
    return ""


def _ouvertes():
    return [task["id"] for task in tasks.list_tasks()]


def _integre(repo):
    """Le merge que l'humain finit par faire : après ça, la branche ne porte plus rien."""
    _git(repo, "merge", "--no-ff", "agent/t1", "-m", "merge du travail de l'agent")


def test_une_livraison_non_integree_garde_la_tache_ouverte(repo):
    _seed("proj", "t1", repo)

    _ticks(2)

    task_id = _task_id("proj", "t1")
    assert task_id, "un ticket qui porte du travail non intégré doit être enrôlé en tâche"
    assert task_id in _ouvertes(), "il reste un acte à faire (intégrer) : la tâche reste ouverte"


def test_une_fois_integre_la_tache_se_clot_toute_seule(repo):
    _seed("proj", "t1", repo)
    _ticks(2)
    task_id = _task_id("proj", "t1")
    assert task_id in _ouvertes()

    _integre(repo)
    # Deux tours encore : le premier remet le compte à zéro (ingestion), le second clôt.
    _ticks(2)

    assert task_id not in _ouvertes(), (
        "plus rien à intégrer, aucun point ouvert : la tâche ne doit plus encombrer le board"
    )
    closes = [task for task in tasks.list_tasks(include_closed=True) if task["id"] == task_id]
    assert closes, "clôturée ne veut pas dire supprimée : elle reste consultable"
    assert closes[0]["outcome"] == "fait"


def test_une_carte_moot_ne_laisse_pas_de_decision_ouverte(repo):
    _seed("proj", "t1", repo)
    _ticks(2)
    assert [row for row in decisions.open_decisions()
            if row["situation"] == decision_ingest.SITUATION_UNMERGED], (
        "le travail non intégré doit s'être matérialisé en décision à prendre"
    )

    _integre(repo)
    _ticks(2)

    assert not [row for row in decisions.open_decisions()
                if row["situation"] == decision_ingest.SITUATION_UNMERGED], (
        "une décision devenue sans objet sort des décisions ouvertes (moot, jamais DELETE)"
    )


def test_une_question_d_agent_en_attente_empeche_la_cloture(repo):
    _seed("proj", "t1", repo)
    _ticks(2)
    task_id = _task_id("proj", "t1")

    decisions.upsert(
        source="agent_question",
        situation="question_agent",
        question="Faut-il garder l'ancien endpoint ?",
        asked_at="2026-08-25T09:00:00",
        task_id=task_id,
        project_slug="proj",
        ticket_id="t1",
        agent_id="a1",
        context="",
        options=[{"key": "garder", "label": "Garder"}, {"key": "retirer", "label": "Retirer"}],
        allow_freetext=True,
        recommended="",
        urgency=0,
        bucket="q1",
    )
    _integre(repo)
    _ticks(2)

    assert task_id in _ouvertes(), (
        "plus rien à intégrer, mais un humain doit encore répondre : la tâche RESTE ouverte"
    )
