# [desc] Board et arbre des agents ne se contredisent plus sur le même instant. [/desc]
"""Deux vues du même état, deux réponses opposées (cas vécu 28/07).

Au même instant, pour les tickets a88aeb4c / e03adb3b / 1f24b202 :
  * `GET /api/projects/<slug>/tickets` renvoyait `liveness_state = "stalled"` ;
  * `GET /api/agents/tree` renvoyait `state=finished, liveness=delivered, rc=0`.
De quoi annoncer à tort que les agents étaient plantés.

Il n'y avait pourtant qu'UNE cause : `classify_ticket` appelait « stalled » l'état
NORMAL d'un ticket dont le codeur a livré et dont personne n'a encore décidé la suite
(depuis le retrait de la chaîne automatique, c'est l'issue de TOUS les tickets). Le
mot disait « bloqué » là où l'arbre disait « livré ». `awaiting_decision` nomme
désormais cette attente. Lot L2 : il n'y a plus qu'UN état (`ticket.state`), que l'arbre et
la liste lisent tous deux — `delivered`, « À vérifier »."""
from __future__ import annotations

from bouzecode.web_v2.services.work import fleet, tickets, wake

from delivery_repo import (  # noqa: F401 — fixtures pytest
    CODEUR, SLUG, agents_dir, client, delivered_ticket, develop_repo, finished_agent, project,
)


def test_the_board_and_the_agent_tree_no_longer_contradict_each_other(
        client, project, agents_dir):
    """Le board annonce une DÉCISION à prendre pendant que l'arbre annonce une livraison :
    deux faits complémentaires, plus aucun mot suggérant un plantage."""
    ticket = delivered_ticket(project, "cloisonne le dashboard")
    finished_agent(agents_dir, ticket["worktree"]["worktree"], ticket["id"])
    wake.tick()  # le watchdog constate la livraison ; la lecture ne fait que lire

    rows = client.get(f"/api/projects/{SLUG}/tickets").get_json()["tickets"]
    row = next(r for r in rows if r["id"] == ticket["id"])
    node = next(n for n in fleet.agent_tree()["nodes"] if n["agent_id"] == CODEUR)

    assert node["liveness"] == "delivered"               # le RUN a livré
    assert row["state"] == "delivered"                   # le TICKET attend une décision
    assert row["status"] == "à relire"
    assert node["interrupted"] is False
    #  Lot L2 : l'arbre dit l'état du TICKET mot pour mot, celui de la liste.
    assert (node["ticket_state"], node["libelle_ticket"]) == (row["state"], row["libelle_statut"])


def test_neither_the_board_nor_the_watchdog_commits_a_delivery(client, project, agents_dir):
    """Bout en bout : consulter le board ne commite RIEN (spec ticketing B1, constat C1), et
    le tick du watchdog non plus (B4, lot L4) : il constate la livraison. Seule une
    intégration demandée commitera le travail, juste avant le merge."""
    from delivery_repo import git_out
    ticket = delivered_ticket(project, "vidéos Focus", produced="vtt.py")
    finished_agent(agents_dir, ticket["worktree"]["worktree"])
    branch = ticket["worktree"]["branch"]

    client.get(f"/api/projects/{SLUG}/tickets")
    wake.tick()

    assert git_out(project, "diff", "--name-only", f"develop...{branch}") == ""
    stored = tickets.get_ticket(SLUG, ticket["id"])
    assert stored["worktree"]["non_commites"] == ["vtt.py"]
