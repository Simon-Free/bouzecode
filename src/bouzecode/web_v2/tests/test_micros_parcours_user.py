"""Le parcours que l'utilisateur a demandé (docs/bureau-todo-modele-et-api.md, §8 à §10), joué
de bout en bout comme il le vivrait dans le navigateur : je note une idée en une ligne, j'y
reviens plus tard, je précise, je fais proposer l'assistant et j'arbitre, puis — et seulement
alors — je lance.

Tout passe par les VRAIES routes HTTP et la vraie base SQLite (isolée par la fixture autouse
`_isolate_production_state` du conftest). Aucun mock : ce qui est vérifié ici est ce que
l'utilisateur peut réellement faire.

Ce que chaque test PROUVE, dans les termes de la spec :

- E1 « écrire un TODO prend du temps »  -> une capture naît en `brouillon` et rien ne la lance.
- E4 « une micro n'est pas résumable en une ligne » -> titre court ET corps markdown long.
- E2 « ajouter des précisions, en faire ajouter par l'assistant » -> historique append-only,
  proposition de l'assistant en attente de MON arbitrage.
- L'invariant qui RESTE (demande utilisateur du 2026-09-08) -> `lancer` exige un TITRE (sans
  quoi personne ne sait quoi faire), mais PLUS un dépôt : à défaut, le lancement se replie sur
  le dépôt par défaut `demo`. Remplir le dépôt est une précision, pas un péage.
- E3 « retrouver la répartition micro / macro » -> une macro est un objet qui traverse
  PLUSIEURS dépôts, pas une chaîne recopiée par chaque agent.
"""
import pytest

from bouzecode.web_v2.app import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _capture(client, saisie):
    """Ce que fait la zone « + Ajouter une tâche… » du Bureau : une ligne tapée, rien de plus."""
    response = client.post("/api/micros", json={"titre": saisie})
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()


def _micro(client, titre, **body):
    response = client.post("/api/micros", json={"titre": titre, **body})
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["micro"]


def _lu(client, micro_id):
    response = client.get(f"/api/micros/{micro_id}")
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["micro"]


# --------------------------------------------------------------------------- E1


def test_je_note_une_idee_et_rien_ne_part_tout_seul(client):
    """E1 : la capture est un DÉBUT. Elle crée un brouillon, elle ne lance aucun agent."""
    capture = _capture(client, "refaire le décodeur TRAF")
    micro_id = capture["micro"]["id"]

    micro = _lu(client, micro_id)
    assert micro["etat"] == "brouillon"
    assert micro["titre"] == "refaire le décodeur TRAF"
    assert micro["origine"] == "humain"

    #  Ce que la capture NE fait pas : elle n'a lancé aucun ticket toute seule.
    assert micro["tickets"] == []

    #  SPEC v3 §4.7 (2026-09-23) : aucun dépôt n'est DEVINÉ. L'ancien repli silencieux sur
    #  `demo` faisait partir le travail ailleurs que prévu (ou nulle part, quand `demo`
    #  n'était pas enregistré, et l'écran affichait « ticket lancé »). Sans dépôt connu, le
    #  lancement est refusé en le NOMMANT, et la ligne reste un brouillon.
    lance = client.post(f"/api/micros/{micro_id}/lancer", json={})
    assert lance.status_code == 400, lance.get_data(as_text=True)
    assert lance.get_json()["error"]["code"] == "depot_requis"
    assert "dépôt" in lance.get_json()["error"]["message"]
    assert _lu(client, micro_id)["etat"] == "brouillon"
    assert "prete" not in lance.get_data(as_text=True), "plus aucun péage d'état"


def test_creation_et_dispatch_sont_deux_actes_separes(client):
    """§8.3 : même une micro complète ne part pas à la création — il faut me le demander."""
    micro = _micro(client, "migrer demo_table sur databricks", projet_slug="demo_ingestion")
    assert micro["etat"] == "brouillon"
    assert micro["tickets"] == []


# --------------------------------------------------------------------------- E4


def test_titre_court_et_corps_markdown_long(client):
    """E4 : la liste reste lisible (titre d'une ligne) alors que le brief est long."""
    micro = _micro(client, "migrer demo_table")
    corps = (
        "## Contexte\n"
        "La table `demo_table` est alimentée par l'ingestion historique.\n\n"
        "## Ce qu'on sait déjà\n"
        "- le décodeur vit dans `src/ingestion/traf.py`\n"
        "- 12 000 lignes/jour, 3 formats de trame\n\n"
        "## Hors périmètre\n"
        "Ne pas toucher au calcul des indicateurs.\n"
    )
    patched = client.patch(f"/api/micros/{micro['id']}", json={"corps": corps})
    assert patched.status_code == 200, patched.get_data(as_text=True)

    relu = _lu(client, micro["id"])
    assert relu["titre"] == "Contexte"           # une ligne (1re ligne du brief), pour la liste
    assert relu["corps"] == corps                # le brief entier, pour l'agent
    assert relu["etat"] == "brouillon"           # préciser ne rend pas prêt


def test_je_reviens_dessus_autant_de_fois_que_je_veux(client):
    """E1 : `brouillon -> brouillon`, la transition qui compte le plus dans le §8.5."""
    micro = _micro(client, "titre provisoire")
    for essai in ("premier jet", "deuxième jet", "troisième jet"):
        assert client.patch(f"/api/micros/{micro['id']}", json={"corps": essai}).status_code == 200
    relu = _lu(client, micro["id"])
    assert relu["corps"] == "troisième jet"
    assert relu["titre"] == "troisième jet"      # un seul champ : le titre suit le brief
    assert relu["etat"] == "brouillon"


# --------------------------------------------------------------------------- E2


def test_les_precisions_s_empilent_sans_jamais_s_ecraser(client):
    """E2 : append-only. Deux ajouts = deux lignes, dans l'ordre, avec leur auteur."""
    micro = _micro(client, "refaire le décodeur TRAF")
    for texte in ("le format 3 n'est pas documenté", "voir le ticket 4c097964 pour le parseur"):
        ajout = client.post(f"/api/micros/{micro['id']}/precisions",
                            json={"texte": texte, "auteur": "humain"})
        assert ajout.status_code == 201, ajout.get_data(as_text=True)

    precisions = _lu(client, micro["id"])["precisions"]
    assert [item["texte"] for item in precisions] == [
        "le format 3 n'est pas documenté",
        "voir le ticket 4c097964 pour le parseur",
    ]
    assert {item["auteur"] for item in precisions} == {"humain"}
    assert all(item["statut"] == "validee" for item in precisions)


def test_je_peux_jeter_une_precision(client):
    micro = _micro(client, "refaire le décodeur TRAF", projet_slug="demo_ingestion")
    ajoutee = client.post(f"/api/micros/{micro['id']}/precisions",
                          json={"texte": "le décodeur doit rester compatible TRAF v2"})
    assert ajoutee.status_code in (200, 201), ajoutee.get_data(as_text=True)
    precision = ajoutee.get_json()["precision"]
    jetee = client.delete(f"/api/micros/{micro['id']}/precisions/{precision['id']}")
    assert jetee.status_code == 200, jetee.get_data(as_text=True)
    assert _lu(client, micro["id"])["precisions"] == []


# ------------------------------------------------------- le verrou de lancement


def test_prete_est_un_geste_explicite_et_exigeant(client):
    """§10.2 : `pret` refuse un titre vide, ou une micro sans projet NI macro."""
    orpheline = _micro(client, "faire un truc")
    refus = client.post(f"/api/micros/{orpheline['id']}/pret", json={})
    assert refus.status_code == 400, refus.get_data(as_text=True)
    assert _lu(client, orpheline["id"])["etat"] == "brouillon"

    situee = _micro(client, "migrer demo_table", projet_slug="demo_ingestion")
    accepte = client.post(f"/api/micros/{situee['id']}/pret", json={})
    assert accepte.status_code == 200, accepte.get_data(as_text=True)
    assert _lu(client, situee["id"])["etat"] == "prete"


def test_le_brief_envoye_a_l_agent_contient_tout_ce_que_j_ai_ecrit(client):
    """§8.4 : le prompt est assemblé depuis titre + corps + précisions validées."""
    micro = _micro(client, "migrer demo_table", projet_slug="demo_ingestion",
                   corps="La table est alimentée par l'ingestion historique.")
    client.post(f"/api/micros/{micro['id']}/precisions",
                json={"texte": "chemin : src/ingestion/traf.py", "auteur": "humain"})
    prompt = _lu(client, micro["id"])["prompt"]
    assert "migrer demo_table" in prompt
    assert "ingestion historique" in prompt
    assert "src/ingestion/traf.py" in prompt


def test_je_peux_revenir_en_brouillon_depuis_prete(client):
    """§8.5 : `prete -> brouillon`, parce que je veux encore préciser."""
    micro = _micro(client, "migrer demo_table", projet_slug="demo_ingestion")
    client.post(f"/api/micros/{micro['id']}/pret", json={})
    retour = client.post(f"/api/micros/{micro['id']}/etat",
                         json={"etat": "brouillon", "pourquoi": "il manque le format des trames"})
    assert retour.status_code == 200, retour.get_data(as_text=True)
    assert _lu(client, micro["id"])["etat"] == "brouillon"


def test_une_livraison_insuffisante_enrichit_le_brief_au_lieu_de_le_perdre(client):
    """§8.5 : `lancee -> brouillon`, et la raison DEVIENT une précision."""
    micro = _micro(client, "migrer demo_table", projet_slug="demo_ingestion")
    client.post(f"/api/micros/{micro['id']}/pret", json={})
    # On force l'état livré sans passer par un vrai dispatch : ce test parle du RETOUR.
    assert client.post(f"/api/micros/{micro['id']}/etat",
                       json={"etat": "lancee"}).status_code == 200
    renvoi = client.post(f"/api/micros/{micro['id']}/etat",
                         json={"etat": "brouillon", "pourquoi": "les tests ne couvrent pas le format 3"})
    assert renvoi.status_code == 200, renvoi.get_data(as_text=True)

    relu = _lu(client, micro["id"])
    assert relu["etat"] == "brouillon"
    assert "format 3" in relu["precisions"][-1]["texte"]
    assert "format 3" in relu["prompt"]


def test_une_micro_faite_ne_se_relance_pas(client):
    micro = _micro(client, "migrer demo_table", projet_slug="demo_ingestion")
    client.post(f"/api/micros/{micro['id']}/pret", json={})
    client.post(f"/api/micros/{micro['id']}/etat", json={"etat": "lancee"})
    client.post(f"/api/micros/{micro['id']}/etat", json={"etat": "faite"})
    refus = client.post(f"/api/micros/{micro['id']}/lancer", json={})
    assert refus.status_code == 409, refus.get_data(as_text=True)


# --------------------------------------------------------------------------- E3


def test_une_macro_traverse_plusieurs_depots(client):
    """E3 : « Refaire DEMODB sur databricks » n'est pas un projet — elle en touche trois."""
    cree = client.post("/api/macros", json={
        "titre": "Refaire DEMODB sur databricks",
        "corps": "Objectif : sortir de l'Oracle historique.\nHors périmètre : les rapports Excel.",
        "projets": ["demo_ingestion", "demo_monorepo"],
    })
    assert cree.status_code == 201, cree.get_data(as_text=True)
    macro = cree.get_json()["macro"]
    assert sorted(macro["projets"]) == ["demo_ingestion", "demo_monorepo"]
    assert macro["etat"] == "active"

    # Un dépôt s'ajoute EN COURS DE ROUTE : c'est le cas normal d'un chantier de plusieurs mois.
    ajout = client.post(f"/api/macros/{macro['id']}/projets", json={"slug": "demo_application"})
    assert ajout.status_code == 200, ajout.get_data(as_text=True)
    assert "demo_application" in client.get(f"/api/macros/{macro['id']}").get_json()["macro"]["projets"]


def test_renommer_une_macro_ne_casse_pas_les_rattachements(client):
    macro = client.post("/api/macros", json={"titre": "DEMODB databricks"}).get_json()["macro"]
    micro = _micro(client, "migrer demo_table", macro_id=macro["id"], projet_slug="demo_ingestion")

    renomme = client.patch(f"/api/macros/{macro['id']}",
                           json={"titre": "Refaire DEMODB sur databricks"})
    assert renomme.status_code == 200, renomme.get_data(as_text=True)
    assert _lu(client, micro["id"])["macro_id"] == macro["id"]

    detail = client.get(f"/api/macros/{macro['id']}").get_json()["macro"]
    assert detail["titre"] == "Refaire DEMODB sur databricks"
    assert [item["id"] for item in detail["micros"]] == [micro["id"]]


def test_la_liste_des_micros_se_filtre_pour_travailler(client):
    macro = client.post("/api/macros", json={"titre": "DEMODB databricks"}).get_json()["macro"]
    dedans = _micro(client, "migrer demo_table", macro_id=macro["id"], projet_slug="demo_ingestion")
    dehors = _micro(client, "relire la note de Yann")

    par_macro = client.get(f"/api/micros?macro_id={macro['id']}").get_json()["micros"]
    assert [item["id"] for item in par_macro] == [dedans["id"]]

    brouillons = client.get("/api/micros?etat=brouillon").get_json()["micros"]
    assert {dedans["id"], dehors["id"]} <= {item["id"] for item in brouillons}

    par_projet = client.get("/api/micros?projet=demo_ingestion").get_json()["micros"]
    assert [item["id"] for item in par_projet] == [dedans["id"]]


def test_deux_agents_qui_nomment_la_meme_macro_pointent_le_meme_id(client):
    """E3 : fini les sections en double parce que deux agents l'orthographient différemment."""
    premier = _micro(client, "tâche A", macro_titre="Refaire DEMODB sur databricks")
    second = _micro(client, "tâche B", macro_titre="refaire demodb sur databricks")
    assert premier["macro_id"]
    assert premier["macro_id"] == second["macro_id"]
    assert len(client.get("/api/macros").get_json()["macros"]) == 1


# ------------------------------------------------------ G1 : plus de tâche nue


def test_une_tache_nue_ne_peut_plus_etre_creee(client):
    """G1 (§4) : la création exige un projet ET (un ticket ou un pourquoi)."""
    nue = client.post("/api/tasks", json={"title": "faire un truc"})
    assert nue.status_code == 400, nue.get_data(as_text=True)

    sans_pourquoi = client.post("/api/tasks", json={"title": "faire un truc",
                                                    "project_slug": "demo_ingestion"})
    assert sans_pourquoi.status_code == 400, sans_pourquoi.get_data(as_text=True)

    portee = client.post("/api/tasks", json={"title": "migrer demo_table",
                                            "project_slug": "demo_ingestion",
                                            "intent": "sortir de l'Oracle historique"})
    assert portee.status_code == 201, portee.get_data(as_text=True)


# ------------------------------------------------- le front doit rendre ça faisable


def test_lancer_une_tache_dont_le_depot_n_existe_plus_est_refuse_sans_trace(client):
    """Le dépôt de la tâche n'est pas enregistré : refus NOMMÉ, et aucune trace (ni ticket
    rattaché, ni changement d'état). Aucun agent n'est démarré : les deux cas sont des REFUS."""
    micro = _micro(client, "refaire l'ingestion", projet_slug="demo_ingestion")

    refus = client.post(f"/api/micros/{micro['id']}/lancer", json={})
    assert refus.status_code == 400, refus.get_data(as_text=True)
    assert refus.get_json()["error"]["code"] == "depot_inconnu"

    inconnue = client.post("/api/micros/nexistepas/lancer", json={})
    assert inconnue.status_code == 404, inconnue.get_data(as_text=True)

    relue = _lu(client, micro["id"])
    assert relue["tickets"] == []
    assert relue["etat"] == "brouillon"


def test_lancer_accepte_le_profil_choisi_dans_l_ui(client):
    """Le bouton « lancer un agent » du Bureau poste le PROFIL retenu pour la ligne.

    Régression du 2026-09-07 : la route explosait en 500 —
    `TypeError: dispatch() got an unexpected keyword argument 'profile'` — parce que le
    service ne connaissait pas cet argument. Aucun agent ne part ici : le dépôt nommé
    n'existe pas. Depuis la SPEC v3, ce refus est une ERREUR HTTP lisible (400
    `depot_inconnu`), plus un 200 `ok:false` que l'écran prenait pour un succès."""
    micro = _micro(client, "migrer demo_table", projet_slug="depot_inconnu_du_registre")
    lance = client.post(f"/api/micros/{micro['id']}/lancer", json={"profil": "coder"})
    assert lance.status_code == 400, lance.get_data(as_text=True)
    assert lance.get_json()["error"]["code"] == "depot_inconnu"
    assert _lu(client, micro["id"])["tickets"] == [], "un dépôt inconnu ne dispatche rien"
