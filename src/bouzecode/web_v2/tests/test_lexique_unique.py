# [desc] Lexique UNIQUE : une table serveur (services/work/lexique.py) pour tout mot d'état lu par l'utilisateur — servie par /api/lexique, injectée dans chaque page, reprise telle quelle par le JS, et appliquée aux statuts de ticket. [/desc]
"""Trois lexiques coexistaient : statut de ticket (`derive_status` : « à relire », « planté »…),
statut de tâche (« Brouillon », « Décision à prendre », « En échec ») et état d'agent
(« Terminé », « Arrêté sans finir »), plus les mots des motifs (« Planté », « Question »,
« Vérif. KO ») et des compteurs de chantier (« à reprendre », « brouillon(s) »). L'utilisateur
ne savait plus ce que voulait dire « Brouillon » face à « fait ».
"""
import json
import re
from pathlib import Path

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import _status, lexique, tickets

STATIC = Path(__file__).resolve().parents[1] / "static" / "js"


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_un_mot_par_situation_le_meme_partout():
    mot = lambda cle: lexique.LEXIQUE[cle]["mot"]  # noqa: E731
    #  La tâche et l'agent qui la porte disent le même mot.
    assert mot("a_repondre") == mot("awaiting_input")
    assert mot("en_echec") == mot("crashed") == mot(lexique.LEXIQUE_DU_MOTIF["plante"])
    assert mot("en_cours") == mot("running")
    #  Des mots d'action, pas du jargon.
    assert mot("brouillon") == "À lancer"
    assert mot("a_decider") == "À décider"
    assert lexique.libelle_statut("a_relire") == "À vérifier"


def test_chaque_statut_de_ticket_a_son_mot():
    """Tout libellé que `derive_status` peut rendre (relevé dans son source) est traduit."""
    source = Path(_status.__file__).read_text(encoding="utf-8")
    rendus = set(re.findall(r'return "([^"]+)"', source)) | {"terminé", "décision", "à relire"}
    rendus |= {"planté", "merge bloqué", "clôture bloquée", "livraison non commitée", "lancement échoué"}
    manquants = {s for s in rendus if not lexique.statut_ticket(s)}
    assert not manquants
    assert lexique.libelle_ticket("à relire") == "À vérifier"
    assert lexique.libelle_ticket("planté") == "Arrêté sans finir"


def _defauts_js(fichier, motif):
    return dict(re.findall(motif, (STATIC / fichier).read_text(encoding="utf-8")))


def test_les_mots_par_defaut_du_js_sont_ceux_du_serveur():
    """Le JS lit la table injectée ; ses valeurs par défaut (tests, page sans serveur) lui sont
    ÉGALES — sinon deux lexiques renaîtraient."""
    etats = _defauts_js("lib/states.js", r'\n  (\w+): \{ label: "([^"]*)"')
    for cle, label in etats.items():
        if cle != "unknown":
            assert lexique.LEXIQUE[cle]["mot"] == label, cle
    motifs = _defauts_js("bureau/attention.js", r'\n  (\w+): \{ cat: "\w+", mot: "([^"]*)"')
    assert set(motifs) == set(lexique.LEXIQUE_DU_MOTIF)
    for motif, mot in motifs.items():
        assert lexique.LEXIQUE[lexique.LEXIQUE_DU_MOTIF[motif]]["mot"] == mot, motif


@pytest.mark.parametrize("fichier", ["bureau/tache.js", "bureau/chantier.js"])
def test_plus_de_liste_de_mots_parallele(fichier):
    source = (STATIC / fichier).read_text(encoding="utf-8")
    assert "brouillon(s)" not in source and "à reprendre" not in source
    assert 'brouillon: "Brouillon"' not in source


def test_la_table_est_servie_et_injectee_dans_chaque_page(client):
    servie = client.get("/api/lexique").get_json()
    assert servie == json.loads(json.dumps(lexique.table()))
    for page in ("/bureau", "/conversations"):
        html = client.get(page).get_data(as_text=True)
        bloc = re.search(r'<script type="application/json" id="bz-lexique">(.*?)</script>', html, re.S)
        assert bloc, page
        assert json.loads(bloc.group(1))["entrees"]["brouillon"]["mot"] == "À lancer"


def test_l_api_des_tickets_parle_le_meme_lexique(client):
    client.post("/api/projects", json={"slug": "demo", "name": "demo", "path": str(Path.cwd())})
    tickets.update_ticket("demo", {"id": "t1", "title": "Corriger", "prompt": "Corriger", "runs": []})
    #  Le projet peut ne pas être enregistrable ici : on lit la route de détail si elle répond.
    reponse = client.get("/api/projects/demo/tickets/t1")
    if reponse.status_code == 404:
        pytest.skip("projet de démonstration non enregistré dans ce parc isolé")
    corps = reponse.get_json()
    assert corps["status"] == "à faire"
    assert (corps["status_ui"], corps["libelle_statut"]) == ("brouillon", "À lancer")
