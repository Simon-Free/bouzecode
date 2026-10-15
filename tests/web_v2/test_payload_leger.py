"""Le PREMIER fetch de /api/lignes et /api/agents/tree ne porte plus le detail.

Ces deux payloads pesaient 2,5 Mo et 2,0 Mo sur les vraies donnees (rapport_html des
passages pour l'un, `title_full` = le prompt entier pour l'autre), et /api/lignes est
retelecharge toutes les 5-15 s par le poller du Bureau. On verifie donc ici le CONTRAT :
la liste est projetee, le detail reste accessible (route dediee + `?detail=`), et rien
de ce que l'ecran affiche replie n'a disparu.

Le dispositif (base SQLite jetable via `_persistence.TICKETS_DIR`) est celui de
`test_chantiers_reordonnables.py` : on le REUTILISE, on ne le reinvente pas.
"""
import pytest

from tests.web_v2.test_chantiers_reordonnables import _client, _cree_chantier

#  Le serveur `strip()` le brief a l'enregistrement : la valeur ATTENDUE est donc strippee.
CORPS = ("brief tres long " * 30).strip()


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    """(client, macro_id, micro_id) : un chantier avec une ligne qui a un brief."""
    client = _client(tmp_path, monkeypatch)
    macro_id = _cree_chantier(client, "Chantier mesure")
    reponse = client.post("/api/micros",
                          json={"titre": "Ligne mesuree", "corps": CORPS, "macro_id": macro_id})
    assert reponse.status_code in (200, 201), (reponse.status_code, reponse.data)
    charge = reponse.get_json()
    micro = charge.get("micro") or charge
    return client, macro_id, str(micro["id"])


def _lignes(payload):
    plates = list(payload.get("non_rattachees") or [])
    for chantier in payload.get("chantiers") or []:
        plates.extend(chantier.get("lignes") or [])
    return plates


def _ligne(payload, micro_id):
    for ligne in _lignes(payload):
        if str(ligne.get("id")) == str(micro_id):
            return ligne
    raise AssertionError(f"ligne {micro_id} absente du payload : {[l.get('id') for l in _lignes(payload)]}")


def test_lignes_rend_toujours_les_trois_clefs(ctx):
    client, _, _ = ctx
    payload = client.get("/api/lignes").get_json()
    assert {"chantiers", "non_rattachees", "stats"} <= set(payload)
    assert payload["stats"]["lignes"] >= 1


def test_lignes_leger_ne_porte_plus_le_detail(ctx):
    client, _, micro_id = ctx
    ligne = _ligne(client.get("/api/lignes").get_json(), micro_id)
    assert ligne.get("_leger") is True, "la ligne doit se declarer legere (le JS fusionne son detail)"
    for absent in ("prompt", "rapport", "rapport_html", "tickets", "transitions",
                   "texte", "notes", "retours", "classements"):
        assert absent not in ligne, f"{absent} ne doit plus etre servi dans la liste"


def test_lignes_leger_garde_le_brief_pour_la_recherche(ctx):
    """La recherche du Bureau (`bureau/filtre.js` `correspond`) cherche dans titre + brief de
    chaque tache, repliee ou non : une ligne legere sans son brief ne se retrouvait plus par un
    mot de celui-ci (regression du 2026-09-29)."""
    client, _, micro_id = ctx
    ligne = _ligne(client.get("/api/lignes").get_json(), micro_id)
    assert ligne.get("_leger") is True
    assert ligne.get("corps") == CORPS


def test_lignes_leger_garde_ce_que_l_ecran_affiche_replie(ctx):
    client, _, micro_id = ctx
    ligne = _ligne(client.get("/api/lignes").get_json(), micro_id)
    for attendu in ("id", "titre", "statut", "statut_ui", "libelle_statut", "macro_id",
                    "projet_slug", "created_at", "updated_at"):
        assert attendu in ligne, f"{attendu} est lu par le JS a l'etat replie"


def test_lignes_complet_rend_le_payload_entier(ctx):
    client, _, micro_id = ctx
    ligne = _ligne(client.get("/api/lignes?complet=1").get_json(), micro_id)
    assert ligne.get("corps") == CORPS
    assert not ligne.get("_leger")
    assert "passages" in ligne


def test_detail_par_ligne_rend_le_brief_et_les_passages(ctx):
    client, _, micro_id = ctx
    reponse = client.get(f"/api/lignes/{micro_id}")
    assert reponse.status_code == 200, reponse.data
    ligne = reponse.get_json()["ligne"]
    assert ligne["id"] == micro_id
    assert ligne.get("corps") == CORPS
    assert "passages" in ligne


def test_detail_d_une_ligne_inconnue_est_404(ctx):
    client, _, _ = ctx
    assert client.get("/api/lignes/nexiste-pas").status_code == 404


def test_param_detail_sert_les_lignes_depliees_completes(ctx):
    client, _, micro_id = ctx
    payload = client.get(f"/api/lignes?detail={micro_id}").get_json()
    ligne = _ligne(payload, micro_id)
    assert ligne.get("corps") == CORPS, "une tache DEPLIEE doit rester servie complete par le poll"
    assert not ligne.get("_leger")


def test_agent_tree_pagine_et_borne_title_full(ctx):
    client, _, _ = ctx
    reponse = client.get("/api/agents/tree?offset=0&limit=5")
    assert reponse.status_code == 200, reponse.data
    charge = reponse.get_json()
    assert "nodes" in charge and "total_roots" in charge
    assert isinstance(charge["total_roots"], int)
    for node in charge["nodes"]:
        assert len(node.get("title_full") or "") <= 240, node.get("agent_id")
