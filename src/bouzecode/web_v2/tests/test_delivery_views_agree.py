# [desc] Board et arbre des agents ne se contredisent plus sur le même instant. [/desc]
"""Deux vues du même état, deux réponses opposées (cas vécu 28/07).

Au même instant, pour les tickets a88aeb4c / e03adb3b / face0ff1 :
  * `GET /api/projects/<slug>/tickets` renvoyait `liveness_state = "stalled"` ;
  * `GET /api/agents/tree` renvoyait `state=finished, liveness=delivered, rc=0`.
De quoi annoncer à tort que les agents étaient plantés.

Il n'y avait pourtant qu'UNE cause : `classify_ticket` appelait « stalled » l'état
NORMAL d'un ticket dont le codeur a livré et dont personne n'a encore décidé la suite
(depuis le retrait de la chaîne automatique, c'est l'issue de TOUS les tickets). Le
mot disait « bloqué » là où l'arbre disait « livré ». `awaiting_decision` nomme
désormais cette attente, et `stalled` ne reste que pour la vraie anomalie : un travail
livré dont RIEN n'est commité (cf. test_delivery_harvest.py)."""
from __future__ import annotations

from bouzecode.web_v2.services.work import fleet, liveness, workflow

from delivery_repo import (  # noqa: F401 — fixtures pytest
    CODEUR, SLUG, agents_dir, block_git_index, client, delivered_ticket, develop_repo,
    finished_agent, project,
)


def test_the_board_and_the_agent_tree_no_longer_contradict_each_other(
        client, project, agents_dir):
    """Le board annonce une DÉCISION à prendre pendant que l'arbre annonce une livraison :
    deux faits complémentaires, plus aucun mot suggérant un plantage."""
    ticket = delivered_ticket(project, "cloisonne le dashboard")
    finished_agent(agents_dir, ticket["worktree"]["worktree"])

    rows = client.get(f"/api/projects/{SLUG}/tickets").get_json()["tickets"]
    row = next(r for r in rows if r["id"] == ticket["id"])
    node = next(n for n in fleet.agent_tree()["nodes"] if n["agent_id"] == CODEUR)

    assert node["liveness"] == "delivered"               # le RUN a livré
    assert row["liveness_state"] == "awaiting_decision"  # le TICKET attend une décision
    assert row["status"] == "à relire"
    assert node["interrupted"] is False
    assert "stalled" not in (row["liveness_state"], node["liveness"])


def test_listing_the_board_is_what_commits_a_forgotten_delivery(client, project, agents_dir):
    """Bout en bout : la route liste rejoue la chaîne, donc consulter le board suffit à
    mettre en sûreté le travail d'un agent qui a livré sans que rien ne soit commité."""
    from delivery_repo import git_out
    ticket = delivered_ticket(project, "vidéos de démo", produced="vtt.py")
    finished_agent(agents_dir, ticket["worktree"]["worktree"])
    branch = ticket["worktree"]["branch"]
    assert git_out(project, "diff", "--name-only", f"develop...{branch}") == ""

    client.get(f"/api/projects/{SLUG}/tickets")

    assert git_out(project, "diff", "--name-only", f"develop...{branch}") == "vtt.py"


def test_a_stalled_ticket_now_means_a_real_anomaly(develop_repo, agents_dir):
    """`stalled` ne désigne plus l'attente normale d'une décision : il ne reste que pour
    l'anomalie « livré mais rien de commité », qui appelle une intervention.

    La fiche d'agent (`finished_agent`) manquait : sans elle `load_agent` rend None et le
    ticket se classe `missing` — l'anomalie d'INVENTAIRE, qui court-circuite à raison toute
    lecture de la livraison. Un ticket dont on veut lire l'état de livraison doit référencer
    un agent qui existe, comme les deux tests ci-dessus le font déjà."""
    sain = delivered_ticket(develop_repo, "sain", produced="ok.py")
    finished_agent(agents_dir, sain["worktree"]["worktree"])
    workflow.advance(SLUG, sain)
    en_peril = delivered_ticket(develop_repo, "en péril", produced="perdu.py")
    block_git_index(en_peril["worktree"]["worktree"])
    workflow.advance(SLUG, en_peril)

    assert liveness.classify_ticket(sain) == "awaiting_decision"
    assert liveness.classify_ticket(en_peril) == "stalled"
