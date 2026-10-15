"""Un agent qui DÉMARRE ne s'annonce pas « fini, à relire » (bug du clic « Lancer »).

Symptôme utilisateur : sur /bureau, cliquer « Lancer un agent » affichait aussitôt la ligne
comme « fini, à relire » avec un rapport vide, alors que l'agent était encore en train de
démarrer. Avant L2, le statut se dérivait de la vivacité du run (`starting` n'était pas reconnu
comme actif). Depuis L2, le statut est la projection de `ticket.state` : le rattachement du run
(`add_run`) fait passer le ticket en `running` (spec §4), quelle que soit la phase de démarrage
du process ; seule une fin de run CONSTATÉE le fait passer « à relire ».
"""
from bouzecode.web_v2.services.work import bureau_lignes, constats
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import en_cours, fiche_agent


def test_run_work_qui_demarre_est_en_cours_pas_a_relire():
    """LE bug : process spawné, session pas encore écrite."""
    ticket = en_cours("proj", "a1")
    fiche_agent("a1", "proj", ticket["id"], returncode=None)
    frais = tickets_svc.get_ticket("proj", ticket["id"])
    assert frais["state"] == etats.RUNNING
    assert tickets_svc.derive_status(frais) == "en cours"


def test_run_work_running_reste_en_cours():
    """Non-régression du cas nominal : un passage du watchdog sur un agent vivant ne change rien."""
    import os
    ticket = en_cours("proj", "a1")
    fiche_agent("a1", "proj", ticket["id"], pid=os.getpid(), ipc={"status": "running"})
    constats.constater("proj", tickets_svc.get_ticket("proj", ticket["id"]))
    assert tickets_svc.derive_status(tickets_svc.get_ticket("proj", ticket["id"])) == "en cours"


def test_run_work_fini_est_a_relire():
    """Tour FINI avec réponse finale (agent chaud et joignable ou non) : quelque chose à relire."""
    ticket = en_cours("proj", "a1")
    constats.fin_de_run("proj", ticket["id"], "a1", "final_answer", final_answer=True)
    assert tickets_svc.derive_status(tickets_svc.get_ticket("proj", ticket["id"])) == "à relire"


def test_ticket_sans_etat_n_est_pas_actif():
    """Un dict sans `state` ne se déclare jamais actif : l'état n'est jamais deviné des runs."""
    ticket = {"id": "t", "runs": [{"kind": "work", "state": "running"}]}
    assert tickets_svc.derive_status(ticket) not in ("en cours", "préparation")


def test_ligne_lancee_dont_le_ticket_demarre_reste_en_cours():
    """Vue Bureau : une ligne `lancee` dont le seul ticket est en démarrage ne doit pas
    basculer en `("inactif", "a_relire")` (ce qui déclenche le rapport « Aucun rapport »)."""
    ligne = {"etat": "lancee",
             "tickets": [{"ticket_id": "t", "statut": "en cours"}]}
    assert bureau_lignes._tickets_encore_actifs(ligne) is True
