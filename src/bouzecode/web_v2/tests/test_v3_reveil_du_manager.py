"""Une tâche qui a délégué ne passe « À vérifier » qu'une fois que son agent a RELU ses
sous-agents, c'est-à-dire quand son dernier TOUR s'est clos après leur fin.

Constat du 2026-09-24 (E2E « manager en worktree ») : la tâche est passée « À vérifier » à
19:35:15, neuf secondes avant le réveil du manager qui devait intégrer les lots de ses enfants.
Rejoué au bac à sable avec une sonde à 0,25 s :

    20:07:25.44  le manager clôt son tour de délégation (IPC `idle`, process gardé chaud)
    20:07:27.09  enfant A fini            20:07:27.24  enfant B fini
    20:07:29.9   tâche « À vérifier »     ← manager chaud : `finished_at` vide
    20:07:30.56  mort du process CONSTATÉE (`finished_at`), après les enfants
    20:07:38.9   réveil du manager (tick de 8 s), qui intègre les lots

La comparaison se faisait avec la fin du PROCESS du manager (`finished_at`, heure à laquelle le
serveur remarque sa mort, vide tant qu'il reste chaud) au lieu de la fin de son TOUR, que le
process écrit lui-même dans son IPC.

On fabrique l'état réel sur disque (fiche, session, IPC, tickets) et on lit `GET /api/lignes`.
"""
from bouzecode.web_v2.services.work import tickets
from bouzecode.web_v2.tests.test_v3_statut_des_taches import (  # noqa: F401
    SLUG, client, ecrire_agent, ligne, tache_lancee,
)

MANAGER = "3c3c3c3c3c3c"
ENFANT = "4d4d4d4d4d4d"


def _delegation(fin_enfant: str) -> str:
    """Une tâche lancée dont l'agent a délégué un lot ; le sous-agent a fini à `fin_enfant`."""
    micro_id, _ = tache_lancee("déléguer un lot", MANAGER)
    enfant = tickets.create_ticket(SLUG, "lot A", "lot A")
    enfant.update(parent=MANAGER)
    tickets.update_ticket(SLUG, enfant)
    tickets.add_run(SLUG, enfant, ENFANT, "work", "m")
    ecrire_agent(ENFANT, ticket_id=enfant["id"], final={"answer": "lot A fait"},
                 finished_at=fin_enfant)
    return micro_id


def test_manager_reste_chaud_et_enfant_fini_apres_son_tour_la_tache_reste_en_cours(client):
    """Le cas mesuré : le manager a rendu la main, son process reste chaud, l'enfant finit
    ensuite. Tant que le réveil n'a pas eu lieu, rien n'est à vérifier."""
    micro_id = _delegation(fin_enfant="2026-09-23T10:07:27.089744Z")
    ecrire_agent(MANAGER, vivant=True, ipc="idle", final={"answer": "Lot délégué, j'attends."},
                 tour_fini_a="2026-09-23T10:07:25.440000Z")

    assert ligne(client, micro_id)["statut_ui"] == "en_cours"


def test_mort_du_manager_constatee_apres_ses_enfants_ne_vaut_pas_relecture(client):
    """Le tour du manager s'est clos AVANT la fin de l'enfant ; sa mort n'est constatée
    qu'ensuite. C'est la fin du tour qui compte, pas l'heure du constat."""
    micro_id = _delegation(fin_enfant="2026-09-23T10:07:27.089744Z")
    ecrire_agent(MANAGER, final={"answer": "Lot délégué, j'attends."},
                 tour_fini_a="2026-09-23T10:07:25.440000Z",
                 finished_at="2026-09-23T10:07:30.558910Z")

    assert ligne(client, micro_id)["statut_ui"] == "en_cours"


def test_enfant_fini_dans_la_meme_seconde_mais_apres_le_tour(client):
    """Même seconde, mais l'enfant a fini après le tour du manager : il n'a pas été relu."""
    micro_id = _delegation(fin_enfant="2026-09-23T10:07:25.900000Z")
    ecrire_agent(MANAGER, vivant=True, ipc="idle", final={"answer": "Lot délégué, j'attends."},
                 tour_fini_a="2026-09-23T10:07:25.100000Z")

    assert ligne(client, micro_id)["statut_ui"] == "en_cours"


def test_enfant_fini_avant_le_tour_du_manager_la_tache_est_a_verifier(client):
    """L'enfant a fini, puis le manager a clos un tour (il l'a relu) : c'est à vérifier,
    que le process du manager soit encore chaud ou mort depuis."""
    micro_id = _delegation(fin_enfant="2026-09-23T10:07:27.089744Z")
    ecrire_agent(MANAGER, vivant=True, ipc="idle", final={"answer": "Lots relus et intégrés."},
                 tour_fini_a="2026-09-23T10:07:40.530000Z")
    assert ligne(client, micro_id)["statut_ui"] == "a_relire"

    ecrire_agent(MANAGER, final={"answer": "Lots relus et intégrés."},
                 tour_fini_a="2026-09-23T10:07:40.530000Z",
                 finished_at="2026-09-23T10:07:46.951694Z")
    assert ligne(client, micro_id)["statut_ui"] == "a_relire"


def test_enfant_fini_pendant_un_tour_du_manager_la_tache_reste_en_cours(client):
    """Le manager travaille encore (réveillé, il relit ses lots) : la tâche est en cours."""
    micro_id = _delegation(fin_enfant="2026-09-23T10:07:27.089744Z")
    ecrire_agent(MANAGER, vivant=True, ipc="running")

    assert ligne(client, micro_id)["statut_ui"] == "en_cours"


def test_process_chaud_expire_apres_ses_enfants_garde_la_fin_de_son_tour(client, monkeypatch):
    """Le process chaud du manager expire (TTL) APRÈS la fin de l'enfant : son IPC passe
    `finished` à ce moment-là, mais c'est la fin de son TOUR qui dit s'il a relu l'enfant."""
    from datetime import datetime

    from bouzecode.web_v2.runtime import ipc
    from bouzecode.web_v2.runtime.runner import agent_fiche

    def epoch(iso):
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()

    micro_id = _delegation(fin_enfant="2026-09-23T10:07:27.089744Z")
    ecrire_agent(MANAGER, vivant=True, ipc="running")
    paths = ipc.from_dir(agent_fiche.load_agent(MANAGER).ipc_dir)
    #  Horloge du process : son tour se clôt à 10:07:25.44 (écriture `idle`), puis le TTL
    #  échoit à 10:22:25 sans qu'aucun message ne soit arrivé (écriture `finished`).
    instants = iter([epoch("2026-09-23T10:07:25.440000Z"), epoch("2026-09-23T10:22:25Z")])
    with monkeypatch.context() as m:
        m.setattr(ipc.time, "time", lambda: next(instants))
        ipc._wait_for_followup(paths, ttl_seconds=-1, poll_interval=0)
    etat = ipc.read_state(paths)

    assert etat["status"] == "finished"
    assert etat["fin_de_tour"] == epoch("2026-09-23T10:07:25.440000Z")
    assert ligne(client, micro_id)["statut_ui"] == "en_cours"
