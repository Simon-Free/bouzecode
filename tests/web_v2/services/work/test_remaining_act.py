"""L'ACTE RESTANT d'un ticket livré (commits non intégrés, points ouverts) décide si sa tâche
se clôt toute seule — sans changer le statut du ticket, qui reste la projection de son état.

`à relire` mesurait l'attention : sur 56 tickets ainsi étiquetés, 34 n'avaient RIEN à intégrer.
Lot L2 : le statut d'un ticket est `etat_ticket.statut(state)` ; l'acte restant
(`_status.remaining_of`, mesuré par le tick) ne sert plus qu'à clore la TÂCHE du Bureau qui
l'enveloppe (`task_migration._is_finished`). Tests PURS : aucun store, aucun mock.
"""
from __future__ import annotations

from bouzecode.web_v2.services.work._status import derive_status, remaining_of
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.services.work.task_migration import _is_finished

RIEN = {"unmerged_commits": 0, "open_points": 0}


def _livre(**champs) -> dict:
    return {"id": "t1", "title": "t", "state": etats.DELIVERED, "state_reason": None,
            "runs": [{"kind": "work", "state": "ended"}], **champs}


def test_le_statut_d_un_ticket_livre_ne_depend_pas_de_l_acte_restant():
    assert derive_status(_livre()) == derive_status(_livre(unmerged_commits=3)) == "à relire"


def test_des_commits_non_integres_retiennent_la_tache():
    assert _is_finished(_livre(unmerged_commits=3)) is False


def test_un_point_ouvert_declare_retient_la_tache():
    assert _is_finished(_livre(), open_points=1) is False


def test_ni_commits_ni_points_la_tache_se_clot():
    """Les 34 « à relire » sans livraison : leur tâche se clôt."""
    assert _is_finished(_livre()) is True


def test_un_ticket_clos_est_fini_un_ticket_en_echec_jamais():
    assert _is_finished({"state": etats.CLOSED, "state_reason": {"code": "accepte"}}) is True
    for state, code in ((etats.STOPPED, "crashed"), (etats.LAUNCH_FAILED, "lancement_echoue"),
                        (etats.DELIVERED, "merge_bloque"), (etats.DELIVERED, "cloture_bloquee"),
                        (etats.RUNNING, None), (etats.CREATED, None)):
        assert _is_finished({"state": state, "state_reason": {"code": code} if code else None}) \
            is False, (state, code)


def test_remaining_of_lit_le_compte_memorise_sur_le_ticket():
    """`unmerged_commits` est écrit sur le ticket par le scan git du tick, jamais recalculé
    dans le chemin de lecture du board (budget 300 ms, git interdit)."""
    assert remaining_of(_livre(unmerged_commits=4)) == {"unmerged_commits": 4, "open_points": 0}
    assert remaining_of(_livre(), open_points=2) == {"unmerged_commits": 0, "open_points": 2}
    assert remaining_of(_livre()) == RIEN
    assert remaining_of(_livre(unmerged_commits="beaucoup")) == RIEN
