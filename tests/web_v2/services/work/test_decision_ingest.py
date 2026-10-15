"""L'ingest dit l'ACTE RESTANT : une livraison non intégrée ouvre UNE carte de décision.

Vrai dépôt git temporaire, vraie base SQLite (isolée par la fixture autouse du conftest racine),
aucun mock : le seul juge acceptable d'un module dont le métier est de lancer `git rev-list`.
"""

from __future__ import annotations

import pytest

from bouzecode.web_v2.services.work import (decision_ingest, decisions, task_migration,
                                            tickets)
from bouzecode.web_v2.tests.aides_tickets import semer
from tests.git_modeles import git as _git
from tests.git_modeles import livraison_non_integree


@pytest.fixture
def repo(tmp_path, depot_modele):
    """Un dépôt avec `develop` (1 commit) et `agent/t1` (1 commit de plus) : exactement la
    situation des 22 tickets du parc dont la branche porte du travail non intégré."""
    return depot_modele(tmp_path / "repo", livraison_non_integree, "develop", "agent/t1")


def _seed(slug, ticket_id, repo, *, state="pending", done=True, branch="agent/t1"):
    ticket = {
        "id": ticket_id,
        "title": "Corriger le poller",
        "done": done,
        "worktree": {"repo_root": str(repo), "base": "develop",
                     "branch": branch, "state": state},
    }
    tickets.update_ticket(slug, ticket)
    return ticket


def _cartes(situation=decision_ingest.SITUATION_UNMERGED):
    return [row for row in decisions.open_decisions() if row["situation"] == situation]


def test_une_livraison_non_integree_ouvre_une_carte(repo):
    _seed("proj", "t1", repo)

    compte = decision_ingest.ingest()

    assert compte["scanned"] == 1
    assert compte["unmerged"] == 1
    cartes = _cartes()
    assert len(cartes) == 1
    carte = cartes[0]
    assert carte["source"] == "situation"
    assert carte["urgency"] == 1
    assert carte["ticket_id"] == "t1"
    assert carte["project_slug"] == "proj"
    assert "agent/t1" in carte["question"]
    assert "develop" in carte["question"]
    assert carte["question"].startswith("Travail jamais intégré")  # le mécanisme est nommé
    assert [opt["key"] for opt in carte["options"]] == [
        "integrer", "corriger", "valider", "abandonner"]
    assert carte["recommended"] == "integrer"
    assert carte["allow_freetext"] is True


def test_un_ticket_interrompu_se_recommande_a_la_correction(repo):
    _seed("proj", "t1", repo, done=False)

    decision_ingest.ingest()

    assert _cartes()[0]["recommended"] == "corriger"


def test_deux_ticks_ne_dupliquent_pas_la_carte(repo):
    _seed("proj", "t1", repo)

    premier = decision_ingest.ingest()
    second = decision_ingest.ingest()

    assert len(_cartes()) == 1
    # Mémoïsation sur le tip : le second tick ne relance AUCUN git.
    assert premier["scanned"] == 1
    assert second["scanned"] == 0
    assert second["skipped"] == 1


def test_une_branche_integree_classe_la_carte_sans_la_supprimer(repo):
    _seed("proj", "t1", repo)
    decision_ingest.ingest()
    carte_id = _cartes()[0]["id"]

    # Le manager intègre : le ticket passe à `closed{integre}` (lot L2), plus rien à décider.
    semer("proj", "t1", "closed", "integre", title="Corriger le poller",
          worktree={"repo_root": str(repo), "base": "develop", "branch": "agent/t1"})
    compte = decision_ingest.ingest()

    assert compte["moot"] == 1
    assert _cartes() == []
    survivante = decisions.get(carte_id)
    assert survivante is not None
    assert survivante["delivery"] == "moot"
    assert survivante["answered_at"] == ""


def test_un_merge_reel_fait_disparaitre_la_carte(repo):
    _seed("proj", "t1", repo)
    decision_ingest.ingest()
    assert len(_cartes()) == 1

    _git(repo, "merge", "--no-edit", "agent/t1")
    compte = decision_ingest.ingest()

    assert compte["scanned"] == 1  # le tip de develop a bougé, on remesure
    assert compte["moot"] == 1
    assert _cartes() == []


def test_un_ticket_sans_worktree_n_ouvre_rien():
    tickets.update_ticket("proj", {"id": "t9", "title": "Sans branche", "done": True})

    compte = decision_ingest.ingest()

    assert compte["unmerged"] == 0
    assert compte["scanned"] == 0
    assert _cartes() == []


def test_un_ticket_archive_est_ignore(repo):
    ticket = _seed("proj", "t1", repo)
    ticket["archived"] = True
    tickets.update_ticket("proj", ticket)

    compte = decision_ingest.ingest()

    assert compte == {"scanned": 0, "skipped": 0, "unmerged": 0, "moot": 0, "questions": 0}
    assert _cartes() == []


def _question_d_agent(monkeypatch, project_slug=""):
    """Un agent bloqué sur une question, tel que le rend `awaiting` sur le parc réel."""
    from bouzecode.web_v2.services.work import awaiting
    monkeypatch.setattr(awaiting, "agents_awaiting_answer", lambda: [{
        "project_slug": project_slug, "ticket_id": "t1", "agent_id": "a1",
        "question": "Quel format ?", "asked_at": "2026-09-01T10:00:00+00:00", "title": "t"}])


def _carte_question():
    [carte] = _cartes("question_agent")
    return carte


@pytest.mark.parametrize("slug_vu_par_l_agent", ["", "autre-projet"])
def test_une_question_sans_projet_connu_trouve_quand_meme_sa_tache(repo, monkeypatch,
                                                                  slug_vu_par_l_agent):
    """Mesuré sur le parc réel : `awaiting` rend `project_slug=""` quand le projet de l'agent
    n'est pas dans la liste. La carte naissait alors avec `task_id=""`, donc non comptée par
    `count_open_by_task` — et une question en attente depuis 21 jours ne retenait plus la
    clôture automatique de sa tâche."""
    from bouzecode.web_v2.services.work import tasks
    # `done=False` : la migration écarte les tickets déjà « terminé ». Le cas réel est bien un
    # ticket vivant dont la tâche est OUVERTE.
    _seed("proj", "t1", repo, done=False)
    task_migration.migrate_tickets_into_tasks()
    tache = next(l["task_id"] for l in tasks.all_links() if l["ticket_id"] == "t1")
    _question_d_agent(monkeypatch, project_slug=slug_vu_par_l_agent)
    decision_ingest.ingest()
    assert _carte_question()["task_id"] == tache


def test_un_ticket_sans_tache_ne_rattache_rien(repo, monkeypatch):
    """Le repli ne doit pas INVENTER de tâche : sans lien, la carte reste orpheline (rattachée
    au tick suivant) plutôt que collée à la tâche d'un autre ticket."""
    _seed("proj", "t1", repo)
    _question_d_agent(monkeypatch, project_slug="proj")
    decision_ingest.ingest()
    assert _carte_question()["task_id"] == ""


def test_le_compte_est_persiste_pour_le_reconcile_suivant(repo):
    _seed("proj", "t1", repo)

    decision_ingest.ingest()

    relu = tickets.get_ticket("proj", "t1")
    assert relu["delivery"]["commits_ahead"] == 1 and relu["delivery"]["code_files_ahead"] == 1
    assert relu["delivery"]["marker"] and "unmerged_commits" not in relu


def test_un_residu_apres_integration_est_nomme_comme_tel(repo):
    """Une branche déjà intégrée qui a reçu du travail APRÈS : la carte le dit (« résidu
    post-intégration »), au lieu de le présenter comme une livraison jamais intégrée."""
    ticket = _seed("proj", "t1", repo)
    tickets.poser("proj", ticket, integration={"merged_at": "2026-10-01T09:00:00"})

    decision_ingest.ingest()

    assert _cartes()[0]["question"].startswith("Résidu post-intégration")
