# [desc] Attendre un enfant (Agent en mode pause, CheckAgentResult(wait=true)) : une seule lecture de son état, celle des garde-fous ; l'attente rend la main dès qu'il ne travaille plus et, si elle expire, dit que le ticket EXISTE. [/desc]
"""Zéro réseau, zéro mock : les fiches d'enfants arrivent par le seam `_web_get` (la route
`/api/agents/<moi>/children`), l'horloge par `sleep` / `now`."""
from __future__ import annotations

from bouzecode.backend.multi_agent import attente_web, enfants, lancement_web, outils_enfants

MOI = "7c7c7c7c7c7c"


def _fiche(etat: str, libelle: str, issue: str = "") -> dict:
    return {"ticket_id": "t1", "slug": "p", "agent_id": "a1", "titre": "scraper",
            "etat": etat, "libelle": libelle, "actif": etat in ("lancement", "en_cours"),
            "branche": "agent/t1", "worktree": "", "issue": issue,
            "lancement": {"tour": 68, "nom": "scraper-fix"}, "objectif": "OBJECTIF : scraper"}


EN_COURS = _fiche("en_cours", "en cours")
LIVRE = _fiche("livre", "fini, livré (non intégré)", "travail LIVRÉ (non validé, non mergé)")


def _serveur(etats: list[dict]):
    """La route /enfants : sert les états l'un après l'autre et compte les lectures."""
    lectures: list[str] = []

    def get(url):
        lectures.append(url)
        return {"children": [etats[min(len(lectures) - 1, len(etats) - 1)]]}

    get.lectures = lectures
    return get


def _horloge():
    ecoule = {"s": 0.0}
    return (lambda: ecoule["s"]), (lambda s: ecoule.__setitem__("s", ecoule["s"] + s))


def _config(get) -> dict:
    return {"_web_agent_dir": f"/tmp/{MOI}.ipc", "_web_get": get}


def test_l_attente_s_arrete_des_que_l_enfant_ne_travaille_plus():
    """Deux lectures « en cours », puis « livré » : trois lectures, et le compte rendu."""
    now, sleep = _horloge()
    get = _serveur([EN_COURS, EN_COURS, LIVRE])

    rendu = enfants.attendre_ticket("t1", lambda: enfants.lire(_config(get))[0],
                                    sleep=sleep, now=now)

    assert len(get.lectures) == 3 and get.lectures[0].endswith(f"/api/agents/{MOI}/children")
    assert "fini, livré" in rendu and "travail LIVRÉ" in rendu


def test_un_enfant_qui_travaille_encore_a_l_expiration_existe_toujours():
    """L'attente expire : le retour dit que le ticket EXISTE, pour qu'il ne soit pas relancé."""
    now, sleep = _horloge()
    get = _serveur([EN_COURS])

    rendu = enfants.attendre_ticket("t1", lambda: enfants.lire(_config(get))[0],
                                    sleep=sleep, now=now, timeout=60)

    assert len(get.lectures) > 1
    assert "EXISTE" in rendu and "ne le redispatche pas" in rendu


def test_du_courrier_interrompt_l_attente():
    """Un message arrive pendant l'attente : le parent est rendu à sa frontière de tour."""
    now, sleep = _horloge()
    courrier = iter([False, True])

    try:
        enfants.attendre_ticket("t1", lambda: [EN_COURS], sleep=sleep, now=now,
                                reveil=lambda: next(courrier, True))
    except attente_web.AttenteInterrompue as reveil:
        assert str(reveil) == "t1"
    else:
        raise AssertionError("le parent aurait dû être réveillé")


def test_agent_en_pause_lit_le_meme_etat_que_check_agent_result_et_les_garde_fous():
    """Essai du 2026-09-25 : l'attente et les garde-fous disaient deux choses du même enfant.
    Enfant oisif (tour clos, process chaud) : « fini, livré » pour les TROIS lectures."""
    get = _serveur([LIVRE])
    config = {**_config(get),
              "_web_dispatch": lambda corps: {"routed": True, "ticket_id": "t1",
                                              "project_slug": "p", "project_name": "p"}}

    pause = lancement_web._spawn_web_ticket_agent({"prompt": "scraper", "background": False}, config)
    verifie = outils_enfants._check_agent_result({"task_id": "t1", "wait": True}, config)

    assert "Verdict de l'enfant :" in pause and "fini, livré" in pause
    assert "fini, livré" in verifie
    assert enfants.actifs(config) == []
    assert enfants.refus_si_enfants_actifs("intégrer", config) == ""
