# [desc] Un instantané de ticket réécrit après un add_run concurrent ne perd jamais le run : le parent d'un sous-agent livré est bien réveillé. [/desc]
"""Recette du 2026-09-24 (scénario composé `manager-worktree`) : l'outil Environment de
l'enfant lit son ticket, le serveur enregistre le run (`add_run`), puis l'enfant réécrit son
instantané (worktree, intégration). Le ticket finissait intégré avec `runs=[]` et `launching`
encore posé → `child_pending_launch` vrai à vie → le manager n'était jamais réveillé et son
travail non commité n'était jamais livré.

Lot L2 : `version` est un verrou optimiste — réécrire un instantané périmé lève
`VersionObsolete` (rien n'est écrasé) ; l'écriture d'un champ passe par `poser`, qui relit la
version fraîche."""
from __future__ import annotations

import pytest

from bouzecode.web_v2.services.work import tickets, wake
from bouzecode.web_v2.services.work._ligne_ticket import VersionObsolete
from bouzecode.web_v2.services.work.fsm import etats

SLUG = "demo"


def _enfant_lance_pendant_une_lecture() -> tuple[dict, dict]:
    """Le serveur marque l'enfant « en lancement », l'agent lit son ticket (instantané), puis
    le serveur enregistre le run — l'instantané ne le connaît pas."""
    enfant = tickets.create_ticket(SLUG, "Enfant A", "Écrire enfant_a.md")
    tickets.set_launching(SLUG, enfant)
    instantane = tickets.get_ticket(SLUG, enfant["id"])
    tickets.add_run(SLUG, enfant, "agent-enfant-a", "work", "")
    return enfant, instantane


def test_reecrire_un_instantane_ne_perd_pas_le_run_ajoute_entre_temps():
    enfant, instantane = _enfant_lance_pendant_une_lecture()
    instantane["worktree"] = {"branch": "agent/x", "retire_at": "2026-09-24T10:00:00"}
    with pytest.raises(VersionObsolete):
        tickets.update_ticket(SLUG, instantane)          # périmé : refusé, rien d'écrasé

    tickets.poser(SLUG, instantane, worktree=instantane["worktree"])  # le bon geste
    frais = tickets.get_ticket(SLUG, enfant["id"])
    assert [r["agent_id"] for r in frais["runs"]] == ["agent-enfant-a"]
    assert frais["state"] == etats.RUNNING               # le lancement est bien fini
    assert frais["worktree"]["retire_at"]                # et l'écriture de l'instantané est gardée


def test_l_enfant_livre_ne_bloque_plus_le_reveil_de_son_parent():
    enfant, instantane = _enfant_lance_pendant_une_lecture()
    tickets.poser(SLUG, instantane, worktree={"branch": "agent/x"})

    frais = tickets.get_ticket(SLUG, enfant["id"])
    assert not wake.child_pending_launch(frais)


def test_une_ecriture_sans_concurrence_reste_inchangee():
    ticket = tickets.create_ticket(SLUG, "Seul", "rien")
    tickets.add_run(SLUG, ticket, "agent-1", "work", "")
    lu = tickets.get_ticket(SLUG, ticket["id"])
    lu["title"] = "Renommé"
    tickets.update_ticket(SLUG, lu)
    frais = tickets.get_ticket(SLUG, ticket["id"])
    assert frais["title"] == "Renommé" and [r["agent_id"] for r in frais["runs"]] == ["agent-1"]
