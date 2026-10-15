# [desc] Livraison d'un agent : la fin du run CONSTATE sans commiter ; la récolte n'a lieu que sur geste demandé, et un arbre sale n'est jamais détruit. [/desc]
"""Lot L4 (spec ticketing §5.7, principes B4 et B9, constat C15), adapté au lot L2.

La fin d'un run livré (`delivered`) CONSTATE seulement ce que l'agent laisse (tête de branche,
fichiers non commités) ; le commit n'a lieu que juste avant une intégration ou un nettoyage
DEMANDÉS, quand aucun run ne tourne. Une récolte demandée qui échoue devient la RAISON de
l'état (`delivered{livraison_non_commitee}`) et rien n'est détruit.

Cas d'origine (28/07, tickets a88aeb4c / e03adb3b) : deux codeurs livrent proprement en
laissant tout leur travail non commité dans leur worktree."""
from __future__ import annotations

from pathlib import Path

from bouzecode.web_v2.services.work import (constats, delivery, integration, nettoyage,
                                             runs_ticket, wake)
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work.fsm import etats

from delivery_repo import (  # noqa: F401 — fixtures pytest
    CODEUR, SLUG, agents_dir, block_git_index, delivered_ticket, develop_repo, finished_agent,
    git_out, project, running_ticket,
)


# ── Fin de run : un constat, aucun commit ─────────────────────────────────────

def test_a_delivered_coder_is_observed_not_committed(develop_repo):
    ticket = delivered_ticket(develop_repo, "cloisonne le dashboard")
    branch = ticket["worktree"]["branch"]
    assert ticket["state"] == etats.DELIVERED
    assert git_out(develop_repo, "diff", "--name-only", f"develop...{branch}") == ""  # RIEN commité
    assert ticket["worktree"]["non_commites"] == ["fix.py"]  # le fait est constaté
    assert not delivery.delivery_at_risk(ticket)  # pas une anomalie : rien ne peut se perdre
    assert tickets_svc.derive_status(ticket) == "à relire"


def test_the_observation_is_done_once(develop_repo):
    """Idempotence : rejouer le constat ne relit pas l'arbre."""
    ticket = delivered_ticket(develop_repo, "vidéos Focus", produced="vtt.py")
    (Path(ticket["worktree"]["worktree"]) / "tard.py").write_text("t = 1\n", encoding="utf-8")
    delivery.record_delivery(SLUG, ticket)
    assert tickets_svc.get_ticket(SLUG, ticket["id"])["worktree"]["non_commites"] == ["vtt.py"]


def test_a_dead_agent_is_reported_stopped_and_its_wip_left_untouched(develop_repo, agents_dir,
                                                                       project):
    """Le crash n'est jamais l'occasion d'un commit d'office : le WIP reste dans le worktree."""
    from bouzecode.web_v2.tests.aides_tickets import fiche_agent
    ticket = running_ticket(develop_repo, "planté", produced="wip.py")
    fiche_agent(CODEUR, SLUG, ticket["id"])
    for _ in range(constats.MORTS_AVANT_CRASH):
        wake.tick()
    assert tickets_svc.get_ticket(SLUG, ticket["id"])["state"] == etats.STOPPED
    branch = ticket["worktree"]["branch"]
    assert "wip.py" not in git_out(develop_repo, "ls-tree", "--name-only", branch)
    assert (Path(ticket["worktree"]["worktree"]) / "wip.py").is_file()


def test_a_ticket_without_worktree_is_never_flagged(develop_repo):
    ticket = tickets_svc.create_ticket(SLUG, "étude de faisabilité", "rends un rapport")
    tickets_svc.add_run(SLUG, ticket, "93af88ef2463", "work", "")
    constats.fin_de_run(SLUG, ticket["id"], "93af88ef2463", "final_answer")
    ticket = tickets_svc.get_ticket(SLUG, ticket["id"])
    assert ticket["state"] == etats.DELIVERED
    assert "worktree" not in ticket and not delivery.delivery_at_risk(ticket)


def test_work_produced_after_a_follow_up_is_observed_again(develop_repo):
    ticket = delivered_ticket(develop_repo, "objections du manager", produced="v1.py")
    (Path(ticket["worktree"]["worktree"]) / "v2.py").write_text("y = 2\n", encoding="utf-8")
    delivery.reopen_for_new_work(SLUG, ticket["id"])
    runs_ticket.signaler(SLUG, ticket["id"], CODEUR, "message")  # reprise chaude
    assert tickets_svc.get_ticket(SLUG, ticket["id"])["state"] == etats.RUNNING
    constats.fin_de_run(SLUG, ticket["id"], CODEUR, "final_answer")
    ticket = tickets_svc.get_ticket(SLUG, ticket["id"])
    assert ticket["state"] == etats.DELIVERED
    assert sorted(ticket["worktree"]["non_commites"]) == ["v1.py", "v2.py"]


# ── La récolte : seulement sur geste demandé ──────────────────────────────────

def test_integrating_harvests_just_before_the_merge(develop_repo):
    ticket = delivered_ticket(develop_repo, "à intégrer", produced="livre.py")
    assert integration.integrate_ticket(SLUG, ticket)["ok"] is True
    assert "livre.py" in git_out(develop_repo, "ls-tree", "--name-only", "develop")
    assert tickets_svc.get_ticket(SLUG, ticket["id"])["state"] == etats.CLOSED


def test_cleanup_harvests_before_destroying_the_worktree(develop_repo):
    ticket = delivered_ticket(develop_repo, "archivé puis nettoyé", produced="precieux.py")
    branch = ticket["worktree"]["branch"]
    assert nettoyage.preparer(SLUG, ticket) == {"ok": True, "a_retirer": True}
    assert nettoyage.retirer(SLUG, ticket["id"]) is True
    assert not Path(ticket["worktree"]["worktree"]).exists()
    assert "precieux.py" in git_out(develop_repo, "ls-tree", "--name-only", branch)
    assert tickets_svc.get_ticket(SLUG, ticket["id"])["worktree"]["retire_at"]


# ── Quand une récolte DEMANDÉE échoue, le ticket le crie et rien n'est détruit ────

def test_a_failed_harvest_refuses_the_cleanup_and_flags_the_ticket(develop_repo, agents_dir):
    """C15 : l'ancien `reap_archived` détruisait (`--force`) un arbre resté sale."""
    ticket = delivered_ticket(develop_repo, "récolte impossible", produced="perdu.py")
    finished_agent(agents_dir, ticket["worktree"]["worktree"])
    block_git_index(ticket["worktree"]["worktree"])
    refus = nettoyage.preparer(SLUG, ticket)
    assert refus["ok"] is False and refus["code"] == "travail_non_recolte"
    assert refus["files"] == ["perdu.py"]
    assert (Path(ticket["worktree"]["worktree"]) / "perdu.py").is_file()  # worktree INTACT
    stored = tickets_svc.get_ticket(SLUG, ticket["id"])
    assert stored["state_reason"]["code"] == delivery.NON_COMMITEE
    assert tickets_svc.derive_status(stored) == "livraison non commitée"


def test_the_flag_is_lifted_once_the_work_is_finally_committed(develop_repo):
    ticket = delivered_ticket(develop_repo, "récolte différée", produced="sauve.py")
    lock = block_git_index(ticket["worktree"]["worktree"])
    nettoyage.preparer(SLUG, ticket)
    assert delivery.delivery_at_risk(tickets_svc.get_ticket(SLUG, ticket["id"]))
    lock.unlink()
    assert nettoyage.preparer(SLUG, tickets_svc.get_ticket(SLUG, ticket["id"]))["ok"] is True
    assert not delivery.delivery_at_risk(tickets_svc.get_ticket(SLUG, ticket["id"]))
    branch = ticket["worktree"]["branch"]
    assert "sauve.py" in git_out(develop_repo, "ls-tree", "--name-only", branch)
