"""`TachesProjet` : tout agent (pas seulement le Bureau) voit la TODO des chantiers de SON projet
et peut la CLASSER (faite / doublon / caduque), commentaire signe. Le reste est au Bureau."""
from __future__ import annotations

import pytest

from bouzecode.backend.core.tool_registry import FRAMEWORK_ALWAYS_ON
from bouzecode.backend.tools import bureau_tools, taches_projet
from bouzecode.web_v2.services.work import micros
from bouzecode.web_v2.tests.test_v3_statut_des_taches import (  # noqa: F401
    FINAL_ANSWER, client, ecrire_agent, ligne, tache_lancee,
)


@pytest.fixture()
def agent(client, monkeypatch):
    """L'outil TachesProjet d'un agent de code du projet « alpha », ticket T-42."""
    monkeypatch.setattr(bureau_tools, "_http", lambda m, chemin, corps=None:
                        client.open(chemin, method=m, json=corps).get_json())
    monkeypatch.setenv("BOUZECODE_TICKET_SLUG", "alpha")
    monkeypatch.setenv("BOUZECODE_TICKET_ID", "T-42")
    return taches_projet.taches_projet


def _ids(rendu):
    assert rendu["ok"], rendu
    return {t["id"] for t in rendu["taches"]}


def test_tout_profil_a_l_outil():
    assert "TachesProjet" in FRAMEWORK_ALWAYS_ON


def test_l_agent_voit_les_taches_de_son_projet_et_pas_celles_d_un_autre(agent):
    chantier = micros.create_macro(titre="Chantier alpha", projets=["alpha"])
    du_chantier = micros.create_micro(titre="Réparer le cache", corps="le cache expire mal",
                                      macro_id=chantier["id"])
    du_depot = micros.create_micro(titre="Logs verbeux", projet_slug="alpha")
    autre = micros.create_micro(titre="Réparer le cache beta", projet_slug="beta")

    vues = agent(action="lister")
    assert _ids(vues) >= {du_chantier["id"], du_depot["id"]}
    assert autre["id"] not in _ids(vues)
    vue = next(t for t in vues["taches"] if t["id"] == du_chantier["id"])
    assert (vue["titre"], vue["chantier"], vue["brief"]) == (
        "Réparer le cache", "Chantier alpha", "le cache expire mal")
    assert vue["statut"]

    trouvees = agent(action="rechercher", texte="cache")
    assert _ids(trouvees) == {du_chantier["id"]}
    assert _ids(agent(action="rechercher", texte="expire")) == {du_chantier["id"]}


def test_l_agent_classe_faite_caduque_doublon_avec_commentaire_signe(client, agent):
    faite = micros.create_micro(titre="A", projet_slug="alpha")
    caduque = micros.create_micro(titre="B", projet_slug="alpha")
    doublon = micros.create_micro(titre="C", projet_slug="alpha")

    sans = agent(action="marquer_faite", task_id=faite["id"])
    assert (sans["ok"], sans["erreur"]) == (False, "commentaire_requis")

    assert agent(action="marquer_faite", task_id=faite["id"],
                 commentaire="résolu par le commit abc123")["ok"]
    assert agent(action="marquer_caduque", task_id=caduque["id"],
                 commentaire="plus d'objet depuis la refonte")["ok"]
    rendu = agent(action="marquer_doublon", task_id=doublon["id"], de=faite["id"],
                  commentaire="même sujet que A")
    assert rendu["ok"], rendu
    assert rendu["classement"]["lien"]["id"] == faite["id"]

    c = ligne(client, faite["id"])["classement"]
    assert (c["auteur"], c["motif"]) == ("agent", "faite")
    assert "ticket T-42" in c["commentaire"] and "commit abc123" in c["commentaire"]
    assert ligne(client, caduque["id"])["classement"]["motif"] == "caduque"
    assert ligne(client, doublon["id"])["classement"]["motif"] == "doublon"
    listees = agent(action="lister", include_closed=True)["taches"]
    vue = next(t for t in listees if t["id"] == faite["id"])
    assert "commentaire d'un agent" in vue["classement"] and "ticket T-42" in vue["classement"]


def test_l_agent_ne_classe_pas_hors_de_son_projet(agent):
    autre = micros.create_micro(titre="Ailleurs", projet_slug="beta")
    rendu = agent(action="marquer_faite", task_id=autre["id"], commentaire="x")
    assert (rendu["ok"], rendu["erreur"]) == (False, "hors_perimetre")


@pytest.mark.parametrize("action", ["creer", "lancer", "relancer", "clore", "repondre",
                                    "deplacer", "preciser"])
def test_l_agent_ne_peut_ni_creer_ni_lancer(agent, action):
    tache = micros.create_micro(titre="D", projet_slug="alpha")
    avant = len(micros.list_micros()) if hasattr(micros, "list_micros") else None
    rendu = agent(action=action, task_id=tache["id"], texte="nouvelle")
    assert (rendu["ok"], rendu["erreur"]) == (False, "action_reservee_au_bureau")
    if avant is not None:
        assert len(micros.list_micros()) == avant
    assert action not in taches_projet.SCHEMA["input_schema"]["properties"]["action"]["enum"]


def test_sans_projet_rattache_reponse_propre(client, agent, monkeypatch):
    monkeypatch.delenv("BOUZECODE_TICKET_SLUG", raising=False)
    micros.create_micro(titre="E", projet_slug="alpha")
    rendu = agent(action="lister")
    assert rendu["ok"] and rendu["taches"] == []
    assert "aucun chantier rattaché" in rendu["message"]


# ── Explorer l'organisation et ranger SA tache (consigne du 2026-10-13 08:00) ──────────────

def test_explorer_rend_projets_et_chantiers_ceux_de_mon_depot_en_premier(agent):
    micros.create_macro("Chantier d'un autre depot", corps="b", projets=["beta"])
    micros.create_macro("Chantier de mon depot", corps="a", projets=["alpha"])

    rendu = agent(action="explorer")

    assert rendu["ok"], rendu
    assert rendu["mes_projets"] == ["alpha"]
    assert isinstance(rendu["projets"], list)
    titres = [c["titre"] for c in rendu["chantiers"]]
    assert titres.index("Chantier de mon depot") < titres.index("Chantier d'un autre depot")
    mien = next(c for c in rendu["chantiers"] if c["titre"] == "Chantier de mon depot")
    assert mien["rattache_a_mon_depot"] is True


def test_l_agent_range_sa_tache_sous_un_chantier_existant(client, agent, monkeypatch):
    chantier = micros.create_macro("Fiabiliser les imports", corps="x", projets=["alpha"])
    mienne, ticket = tache_lancee("Corriger l'import CSV")
    monkeypatch.setenv("BOUZECODE_TICKET_ID", ticket)

    rendu = agent(action="ranger_ma_tache", chantier=chantier["id"])

    assert rendu["ok"], rendu
    assert rendu["chantier"]["id"] == chantier["id"]
    assert micros.get_micro(mienne)["macro_id"] == chantier["id"]


def test_l_agent_cree_un_chantier_signe_puis_y_range_sa_tache(client, agent, monkeypatch):
    mienne, ticket = tache_lancee("Ajouter l'export PDF")
    monkeypatch.setenv("BOUZECODE_TICKET_ID", ticket)

    rendu = agent(action="ranger_ma_tache", creer_chantier=True,
                  chantier_titre="Exports documentaires",
                  chantier_brief="Tous les formats d'export du rapport.")

    assert rendu["ok"], rendu
    assert rendu["chantier_cree"] is True
    cree = rendu["chantier"]
    assert cree["projets"] == ["alpha"]
    assert f"ticket {ticket}" in cree["brief"]  # trace : quel ticket a cree le chantier
    assert micros.get_micro(mienne)["macro_id"] == cree["id"]


def test_pas_de_chantier_en_double_si_un_titre_proche_existe(client, agent, monkeypatch):
    existant = micros.create_macro("Exports documentaires", corps="x", projets=["alpha"])
    mienne, ticket = tache_lancee("Ajouter l'export PDF")
    monkeypatch.setenv("BOUZECODE_TICKET_ID", ticket)
    avant = len(micros.list_macros(etat="active"))

    rendu = agent(action="ranger_ma_tache", creer_chantier=True,
                  chantier_titre="Exports documentaire")

    assert not rendu["ok"]
    assert rendu["erreur"] == "chantier_proche_existe"
    assert [c["id"] for c in rendu["chantiers"]] == [existant["id"]]
    assert len(micros.list_macros(etat="active")) == avant
    assert not micros.get_micro(mienne).get("macro_id")


def test_l_agent_ne_peut_pas_ranger_la_tache_d_un_autre(client, agent, monkeypatch):
    chantier = micros.create_macro("Fiabiliser les imports", corps="x", projets=["alpha"])
    _mienne, ticket = tache_lancee("Ma tache")
    autre = micros.create_micro(titre="La tache d'un autre", projet_slug="alpha")
    monkeypatch.setenv("BOUZECODE_TICKET_ID", ticket)

    rendu = agent(action="ranger_ma_tache", task_id=autre["id"], chantier=chantier["id"])

    assert not rendu["ok"]
    assert rendu["erreur"] == "pas_ta_tache"
    assert not micros.get_micro(autre["id"]).get("macro_id")


def test_sans_ticket_rien_a_ranger(agent, monkeypatch):
    monkeypatch.delenv("BOUZECODE_TICKET_ID", raising=False)
    rendu = agent(action="ranger_ma_tache", chantier="x")
    assert rendu == {**rendu, "ok": False, "erreur": "aucune_tache_en_cours"}
