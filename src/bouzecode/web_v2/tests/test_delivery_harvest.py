# [desc] Un agent qui a LIVRÉ voit son travail commité ; sinon le ticket le crie au lieu de le taire. [/desc]
"""Le trou entre « l'agent a fini » et « son travail existe quelque part ».

Cas vécu (28/07, tickets a88aeb4c / e03adb3b) : deux codeurs finissent proprement
(finished, rc=0, close_reason=final_answer, 19 et 17 tours), leur run est `completed`…
et leur branche `agent/<id>` est VIDE, tout leur travail dormant en non-commité dans
le worktree. La supervision annonçait « livré » un travail qu'un simple archivage du
ticket aurait effacé (`reaper.reap_archived` → `worktree remove --force`).

Cause racine : `worktrees.harvest` — le SEUL geste qui commite le WIP d'un agent —
n'était appelé que depuis la transition CRASH, le merge manuel et le spawn manuel de
validateur. Le correctif aca2f03c (« harvest WIP avant test-gate et sur crash ») en
avait pourtant posé un sur le chemin nominal de SUCCÈS : le test-gate. Le retrait de
la chaîne automatique travail→validation→merge a emporté le test-gate, donc ce
harvest-là ; seul celui du crash a survécu. D'où l'absurdité : un agent qui CRASHE
voit son travail sauvé, un agent qui RÉUSSIT le perd."""
from __future__ import annotations

from pathlib import Path

from bouzecode.web_v2.services.work import delivery, liveness, reaper, workflow
from bouzecode.web_v2.services.work import tickets as tickets_svc

from bouzecode.web_v2.tests.delivery_repo import (  # noqa: F401 — fixtures pytest
    SLUG, agents_dir, block_git_index, delivered_ticket, develop_repo, finished_agent,
    git_out,
)


# ── Le travail livré finit sur la branche ─────────────────────────────────────

def test_a_delivered_coder_gets_its_work_committed_on_its_branch(develop_repo):
    """LE bug : rc=0, run completed, branche vide. La branche porte désormais le travail."""
    ticket = delivered_ticket(develop_repo, "cloisonne le dashboard")
    branch = ticket["worktree"]["branch"]
    assert git_out(develop_repo, "diff", "--name-only", f"develop...{branch}") == ""

    assert workflow.advance(SLUG, ticket) == "delivered"

    assert git_out(develop_repo, "diff", "--name-only", f"develop...{branch}") == "fix.py"
    assert git_out(ticket["worktree"]["worktree"], "status", "--porcelain") == ""
    assert not ticket.get("uncommitted")


def test_the_delivery_harvest_never_commits_twice(develop_repo):
    """Idempotence : la route liste rejoue `advance` en boucle — un seul commit de livraison."""
    ticket = delivered_ticket(develop_repo, "vidéos de démo", produced="vtt.py")
    branch = ticket["worktree"]["branch"]
    workflow.advance(SLUG, ticket)
    commits = int(git_out(develop_repo, "rev-list", "--count", branch))

    assert workflow.advance(SLUG, ticket) is None
    assert int(git_out(develop_repo, "rev-list", "--count", branch)) == commits


def test_a_dead_agent_is_still_reported_as_crashed_not_delivered(develop_repo, monkeypatch):
    """NON-RÉGRESSION : le crash garde la priorité. Récolter aussi les livraisons ne
    transforme pas un run mort sans clôture en livraison."""
    from bouzecode.web_v2.services.work import wake
    monkeypatch.setattr(wake, "process_wakes", lambda: [])
    ticket = delivered_ticket(develop_repo, "planté", produced="wip.py")
    ticket["runs"][0].pop("completed")
    ticket["runs"][0]["pid_alive"] = False
    tickets_svc.update_ticket(SLUG, ticket)

    assert workflow.advance(SLUG, ticket) == "crashed"
    assert ticket["crashed"] is True
    branch = ticket["worktree"]["branch"]
    assert "wip.py" in git_out(develop_repo, "ls-tree", "--name-only", branch)


def test_a_ticket_without_worktree_is_never_flagged(develop_repo):
    """Un ticket `shared` (aucun worktree) n'a rien à récolter : pas d'alerte inventée."""
    ticket = tickets_svc.create_ticket(SLUG, "étude de faisabilité", "rends un rapport")
    tickets_svc.add_run(SLUG, ticket, "93af88ef2463", "work", "")
    tickets_svc.mark_run_completed(SLUG, ticket, "93af88ef2463")
    ticket = tickets_svc.get_ticket(SLUG, ticket["id"])

    assert delivery.needs_delivery_harvest(ticket) is False
    assert workflow.advance(SLUG, ticket) is None
    assert not ticket.get("uncommitted")


# ── Quand la récolte échoue, le ticket le CRIE ────────────────────────────────

def test_a_delivery_whose_harvest_failed_is_flagged_not_announced_as_success(
        develop_repo, agents_dir):
    """Le worktree reste sale après la récolte → le ticket nomme les fichiers en péril et
    son statut refuse d'annoncer un succès.

    La fiche d'agent (`finished_agent`) manquait : sans elle `load_agent` rend None et le
    ticket se classe `missing` — l'anomalie d'INVENTAIRE, qui court-circuite à raison toute
    lecture de la livraison. Pour observer « livré mais en péril », il faut un agent qui
    existe et qui a réellement livré."""
    ticket = delivered_ticket(develop_repo, "récolte impossible", produced="perdu.py")
    finished_agent(agents_dir, ticket["worktree"]["worktree"])
    block_git_index(ticket["worktree"]["worktree"])

    workflow.advance(SLUG, ticket)

    assert ticket["uncommitted"] == ["perdu.py"]
    assert tickets_svc.derive_status(ticket) == "livraison non commitée"
    assert liveness.classify_ticket(ticket) == "stalled"


def test_a_flagged_delivery_cannot_be_repainted_as_finished(develop_repo):
    """Même coché « terminé » à la main, un travail non commité reste signalé : le pire cas
    serait d'afficher « terminé » puis de faucher le worktree."""
    ticket = delivered_ticket(develop_repo, "faux terminé", produced="perdu.py")
    block_git_index(ticket["worktree"]["worktree"])
    workflow.advance(SLUG, ticket)
    ticket["done"] = True

    assert tickets_svc.derive_status(ticket) == "livraison non commitée"


def test_the_flag_is_lifted_once_the_work_is_finally_committed(develop_repo):
    """L'alerte n'est pas collante : le verrou levé, la récolte suivante nettoie le drapeau."""
    ticket = delivered_ticket(develop_repo, "récolte différée", produced="sauve.py")
    lock = block_git_index(ticket["worktree"]["worktree"])
    workflow.advance(SLUG, ticket)
    assert ticket["uncommitted"]

    lock.unlink()
    delivery.harvest_delivery(SLUG, ticket)

    assert not ticket.get("uncommitted")
    branch = ticket["worktree"]["branch"]
    assert "sauve.py" in git_out(develop_repo, "ls-tree", "--name-only", branch)


def test_work_produced_after_a_follow_up_is_harvested_too(develop_repo):
    """Un agent relancé par message garde son run : sans réouverture, sa récolte précédente
    vaudrait quitus à vie et le travail du nouveau tour ne serait jamais commité."""
    ticket = delivered_ticket(develop_repo, "objections du manager", produced="v1.py")
    workflow.advance(SLUG, ticket)
    worktree = Path(ticket["worktree"]["worktree"])
    (worktree / "v2.py").write_text("y = 2\n", encoding="utf-8")  # travail du tour suivant

    delivery.reopen_for_new_work(SLUG, ticket["id"])
    ticket = tickets_svc.get_ticket(SLUG, ticket["id"])
    assert workflow.advance(SLUG, ticket) == "delivered"

    branch = ticket["worktree"]["branch"]
    assert "v2.py" in git_out(develop_repo, "ls-tree", "--name-only", branch)


# ── Le worktree n'est jamais détruit sans récolte ─────────────────────────────

def test_archiving_a_ticket_harvests_before_destroying_its_worktree(develop_repo):
    """`reap_archived` fait `worktree remove --force` : sans récolte préalable, archiver un
    ticket effaçait définitivement le travail non commité de l'agent."""
    ticket = delivered_ticket(develop_repo, "archivé", produced="precieux.py")
    branch = ticket["worktree"]["branch"]

    assert reaper.reap_archived(SLUG, ticket) is True

    assert not Path(ticket["worktree"]["worktree"]).exists()
    assert "precieux.py" in git_out(develop_repo, "ls-tree", "--name-only", branch)
