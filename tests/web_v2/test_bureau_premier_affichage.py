"""Premier affichage du Bureau après un redémarrage : rien de ce qui a déjà été lu n'est relu.

Mesuré le 2026-09-29 sur le parc réel, process neuf : le premier `GET /api/inbox` décodait 712
sessions ENTIÈRES (jusqu'à 112 Mo chacune) pour relire la clôture et le récap d'agents finis
depuis des jours — 12 s servies à l'écran, 63 s cache disque froid. Ces empreintes sont désormais
retenues sur disque par version de fichier (`sessions/empreintes.py`).

On fabrique l'état RÉEL sur disque (fiche, session, IPC, ticket relié à une tâche), on lit
l'écran par HTTP comme le front, puis on simule un process neuf en oubliant toutes les mémoires
de process — les fichiers restent, comme après un redémarrage.
"""
import os
import threading
import time

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.services.sessions import empreintes, meta_index, status_cache, store
from bouzecode.web_v2.services.work import fleet_cache, fleet_vue, projects, taches_vue
from bouzecode.web_v2.tests.test_v3_statut_des_taches import (
    FINAL_ANSWER, ecrire_agent, tache_lancee,
)
from bouzecode.web_v2.tests.aides_tickets import constater_tout

AGENT = "a1b2c3d4e5f6"


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def decodages(monkeypatch):
    """Chemins des sessions décodées (espion sur la lecture publique, qui est appelée)."""
    lus: list[str] = []
    vraie_lecture = store.load_session_json

    def lecture_comptee(path):
        lus.append(str(path))
        return vraie_lecture(path)

    monkeypatch.setattr(store, "load_session_json", lecture_comptee)
    return lus


def _process_neuf():
    """Oublie toutes les mémoires du PROCESS ; les fichiers sur disque restent."""
    empreintes.oublier_tout()
    taches_vue.invalider()
    fleet_cache.clear()
    meta_index.reset_memo()
    status_cache.reset()
    store.invalidate_status(AGENT)
    agent_fiche.invalidate_agents_cache()


def _passage(client, micro_id):
    vue = client.get(f"/api/lignes?detail={micro_id}").get_json()
    for ligne in [x for c in vue["chantiers"] for x in c["lignes"]] + vue["non_rattachees"]:
        if ligne["id"] == micro_id:
            return ligne["passages"][0]
    raise AssertionError(f"tâche {micro_id} absente de /api/lignes")


def _session_de_l_agent(lus):
    return [chemin for chemin in lus if chemin.endswith(f"{AGENT}.session.json")]


def test_un_process_neuf_ne_redecode_aucune_session_deja_vue(client, decodages):
    ecrire_agent(AGENT, final=FINAL_ANSWER)
    micro_id, _ = tache_lancee("corriger le login", AGENT)
    constater_tout()  # lot L2 : la fin du run est CONSTATÉE (watchdog), pas relue à l'écran
    avant = (_passage(client, micro_id), client.get("/api/inbox").get_json())
    assert _session_de_l_agent(decodages), "la première lecture décode la session (rien n'est connu)"

    _process_neuf()
    decodages.clear()
    apres = (_passage(client, micro_id), client.get("/api/inbox").get_json())

    assert _session_de_l_agent(decodages) == []
    assert apres == avant
    assert apres[0]["recap"]["fait"] == ["corriger le login", "ajouter les tests"]
    assert "<" in apres[0]["rapport_html"]


def test_une_session_reecrite_est_relue(client, decodages):
    ecrire_agent(AGENT, final=FINAL_ANSWER)
    micro_id, _ = tache_lancee("corriger le login", AGENT)
    constater_tout()  # lot L2 : la fin du run est CONSTATÉE (watchdog), pas relue à l'écran
    _passage(client, micro_id)

    ecrire_agent(AGENT, final={**FINAL_ANSWER, "taches_terminees": ["tout refaire"]})
    session = agent_fiche.AGENTS_DIR / f"{AGENT}.session.json"
    os.utime(session, (time.time() + 5, time.time() + 5))  # nouvelle version, même à la seconde
    _process_neuf()

    assert _passage(client, micro_id)["recap"]["fait"] == ["tout refaire"]


def test_les_premieres_requetes_simultanees_ne_calculent_l_ecran_qu_une_fois(client, monkeypatch):
    """Le navigateur demande d'un coup /api/inbox, /api/nav/counts et /api/lignes : l'écran
    (contexte des tâches) ne doit être calculé qu'une fois, pas une par requête."""
    monkeypatch.setattr(taches_vue, "CACHE_TTL", 3.0)
    ecrire_agent(AGENT, final=FINAL_ANSWER)
    tache_lancee("corriger le login", AGENT)
    _process_neuf()
    calculs = []
    vrai_contexte = taches_vue.contexte

    def contexte_lent():
        calculs.append(1)
        time.sleep(0.3)  # laisse aux autres requêtes le temps d'arriver pendant le calcul
        return vrai_contexte()

    monkeypatch.setattr(taches_vue, "contexte", contexte_lent)
    depart = threading.Barrier(3)
    statuts = []

    #  L'app est démarrée AVANT la rafale : son boot (migrations des tâches v1) écrit des
    #  tâches et ferait avancer la clé de l'écran pendant le calcul d'une autre requête.
    app = create_app()

    def lire(route):
        depart.wait()
        statuts.append(app.test_client().get(route).status_code)

    fils = [threading.Thread(target=lire, args=(r,))
            for r in ("/api/inbox", "/api/nav/counts", "/api/lignes")]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=30)

    assert statuts == [200, 200, 200]
    assert len(calculs) == 1


def test_la_boite_reste_servie_quand_son_calcul_a_fait_avancer_le_parc(monkeypatch):
    """Lire l'arbre pendant le calcul de la boîte fait avancer la génération du parc (un agent a
    changé de classe) : la boîte tout juste calculée ne doit pas être aussitôt recalculée par
    l'appel suivant (la seconde lente du 2e /api/nav/counts)."""
    monkeypatch.setattr(taches_vue, "CACHE_TTL", 3.0)
    taches_vue.invalider()
    fleet_vue.vider()
    fleet_vue.noter([{"key": "agent/x", "etat": "running"}], time.monotonic(), complet=True)
    calculs = []

    def boite():
        fleet_vue.noter([{"key": "agent/x", "etat": "finished"}], time.monotonic(), complet=True)
        calculs.append(1)
        return {"compte": 0}

    generation = fleet_vue.generation()
    taches_vue.memorise_a_part("boite_de_test", boite)
    assert fleet_vue.generation() == generation + 1
    taches_vue.memorise_a_part("boite_de_test", boite)
    assert len(calculs) == 1


@pytest.mark.parametrize("cwd, attendu", [
    ("C:/depots/demo", "demo"),
    ("C:/depots/demo/sous/dossier", "demo"),
    ("c:\\DEPOTS\\Demo\\src", "demo") if os.name == "nt" else ("/x", None),
    ("C:/depots/demo_application", "appli"),
    ("C:/depots/demo2", None),
    ("", None),
])
def test_le_projet_d_un_agent_est_celui_qui_contient_son_dossier(cwd, attendu):
    """Un dossier appartient au projet qui le CONTIENT — jamais à un voisin dont le nom n'est
    qu'un préfixe (demo vs demo2)."""
    liste = [{"slug": "demo", "path": "C:/depots/demo"},
             {"slug": "appli", "path": "C:/depots/demo_application/"}]
    trouve = projects.project_for_cwd(cwd, liste)
    assert (trouve or {}).get("slug") == attendu
