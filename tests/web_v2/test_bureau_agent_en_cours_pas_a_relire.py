"""Le Bureau ne doit PAS annoncer « fini, à relire » pendant qu'un agent tourne.

Bug constaté par l'utilisateur (08/09) : une micro-tâche basculait en « fini, à relire »
alors que son agent travaillait encore — visible à chaque RELECTURE du Bureau. La cause était
un état de run CALCULÉ à la lecture et absent de la base. Lot L2 : l'état du ticket est
PERSISTÉ (`ticket.state`, écrit par `ticket_fsm`) ; l'index du Bureau en est la projection, il
ne relit plus aucun agent. Tests PURS : tickets injectés, aucune base ni session disque.
"""
from datetime import datetime

from bouzecode.web_v2.services.work import bureau_lignes
from bouzecode.web_v2.services.work.fsm import etats


def _ticket(state: str, code: str | None = None) -> dict:
    return {"id": "t1", "state": state, "state_reason": {"code": code} if code else None,
            "runs": [{"kind": "work", "agent_id": "ag1", "state": "running"}]}


def _statut(ticket: dict) -> str:
    return bureau_lignes._statuts_des_tickets(tickets=[("p", ticket)])[("p", "t1")]["status"]


def test_un_ticket_en_cours_est_en_cours():
    assert _statut(_ticket(etats.RUNNING)) == "en cours"


def test_un_lancement_en_preparation_n_est_pas_a_relire():
    assert _statut(_ticket(etats.PROVISIONING)) in bureau_lignes.STATUTS_ACTIFS


def test_un_agent_qui_attend_une_reponse_reste_actif():
    assert _statut(_ticket(etats.AWAITING_INPUT)) == "attend réponse"


def test_un_manager_qui_attend_ses_enfants_reste_actif():
    assert _statut(_ticket(etats.RUNNING, "attend_enfants")) in bureau_lignes.STATUTS_ACTIFS


def test_un_ticket_livre_est_a_relire():
    assert _statut(_ticket(etats.DELIVERED)) == "à relire"


def test_l_index_porte_l_etat_et_son_libelle():
    """De bout en bout sur l'index consommé par `collect_lignes`."""
    [(cle, projection)] = bureau_lignes._statuts_des_tickets(
        tickets=[("mon-projet", _ticket(etats.RUNNING))]).items()
    assert cle == ("mon-projet", "t1")
    assert (projection["state"], projection["status"], projection["libelle_statut"]) == (
        etats.RUNNING, "en cours", "En cours")


def test_ligne_lancee_reste_en_cours_quand_le_ticket_tourne():
    """La ligne du Bureau suit le statut réel : actif → `en_cours`, sans raison."""
    maintenant = datetime.now()
    ligne = {"etat": "lancee",
             "tickets": [{"statut": "en cours", "at": maintenant.isoformat()}]}
    assert bureau_lignes.statut_de(ligne, maintenant)[0] == "en_cours"
