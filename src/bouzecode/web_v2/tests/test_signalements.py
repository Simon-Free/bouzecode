# [desc] Outil Signaler (non bloquant) : signalement persiste avec agent, profondeur et chaine de parents ; carte « A traiter » + pastille + Flotte ; acquittement ; digest des ancetres au reveil ; sous-agent arrete orphelin dans la boite. [/desc]
from __future__ import annotations

import json
from datetime import datetime

import pytest

from bouzecode.backend.tools import bureau_tools
from bouzecode.backend.tools.signaler import signaler
from bouzecode.web_v2.runtime.runner import agent_fiche, agent_registre
from bouzecode.web_v2.services.work import fleet, inbox, signalements, wake
from bouzecode.web_v2.tests.test_reveil_d_un_enfant_clos import (  # noqa: F401 — fixtures
    ENFANT, PETIT_ENFANT, RACINE, _clos, _ticket, reveils,
)
from bouzecode.web_v2.tests.test_v3_statut_des_taches import client, ecrire_agent  # noqa: F401


def _avec_parent(agent_id: str, parent: str) -> None:
    fiche = agent_fiche.AGENTS_DIR / f"{agent_id}.json"
    donnees = json.loads(fiche.read_text(encoding="utf-8"))
    fiche.write_text(json.dumps({**donnees, "parent": parent}), encoding="utf-8")
    agent_fiche._list_agents_cache.clear()
    agent_registre._agent_file_cache.clear()


@pytest.fixture()
def petit_enfant_web(monkeypatch):
    """Le process du petit-enfant : son IPC, son parent et son ticket, comme le runner les pose."""
    ecrire_agent(RACINE)
    ecrire_agent(ENFANT)
    _avec_parent(ENFANT, RACINE)
    monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", str(agent_fiche.AGENTS_DIR / f"{PETIT_ENFANT}.ipc"))
    monkeypatch.setenv("BOUZECODE_PARENT", ENFANT)
    monkeypatch.setenv("BOUZECODE_TICKET_SLUG", "demo")
    monkeypatch.setenv("BOUZECODE_TICKET_ID", "t-petit")


def _signaler(gravite="bloquant", titre="Quota Databricks atteint"):
    return signaler({"gravite": gravite, "titre": titre, "detail": "job 42 refuse",
                     "action_attendue": "relever le quota"}, {})


def test_signaler_enregistre_l_agent_sa_lignee_et_rend_la_main(petit_enfant_web):
    sortie = _signaler()

    assert "CONTINUE ton travail" in sortie
    (s,) = signalements.ouverts()
    assert (s["agent_id"], s["parents"], s["profondeur"]) == (PETIT_ENFANT, [ENFANT, RACINE], 2)
    assert (s["ticket_slug"], s["ticket_id"], s["gravite"]) == ("demo", "t-petit", "bloquant")


def test_une_gravite_inconnue_est_une_erreur_d_outil(petit_enfant_web):
    assert _signaler(gravite="grave").startswith("Error: signalement refuse")
    assert signalements.ouverts() == []


def test_le_signalement_est_une_carte_a_traiter_compte_et_acquittable(petit_enfant_web, client):
    _signaler("info", "Deux tests flaky ignores")
    _signaler("bloquant")

    cartes = [c for c in client.get("/api/inbox").get_json()["items"]
              if c["type"] == "signalement"]
    assert [(c["gravite"], c["urgence"]) for c in cartes] == [("bloquant", 0), ("info", 2)]
    assert cartes[0]["parents"] == [ENFANT, RACINE] and cartes[0]["profondeur"] == 2
    assert client.get("/api/nav/counts").get_json()["inbox"] >= 2
    vus_par_l_assistant = [c for c in bureau_tools.flotte()["a_traiter"]
                           if c["type"] == "signalement"]
    assert vus_par_l_assistant[0]["gravite"] == "bloquant"

    r = client.post(f"/api/signalements/{cartes[0]['signalement_id']}/acquitter")
    assert r.status_code == 200 and r.get_json()["signalement"]["acquitte_at"]
    restants = [c for c in client.get("/api/inbox").get_json()["items"]
                if c["type"] == "signalement"]
    assert [c["gravite"] for c in restants] == ["info"]
    assert client.post("/api/signalements/inconnu/acquitter").status_code == 404


def test_chaque_ancetre_le_recoit_une_fois_dans_son_digest(petit_enfant_web):
    _signaler()

    for ancetre in (ENFANT, RACINE):
        digest = signalements.digest_pour(ancetre)
        assert "Quota Databricks atteint" in digest and "profondeur 2" in digest
        assert signalements.digest_pour(ancetre) == ""
    assert signalements.digest_pour("etranger") == ""


def test_le_reveil_du_parent_porte_les_signalements_de_sa_lignee(petit_enfant_web, reveils):
    ecrire_agent(RACINE, vivant=True, ipc="running")
    enfant = _ticket("refonte", RACINE, ENFANT)
    petit = _ticket("mesure", ENFANT, PETIT_ENFANT)
    _signaler("alerte", "Mesure partielle : 3 jours sur 7")
    _clos(PETIT_ENFANT, petit["id"])
    _clos(ENFANT, enfant["id"], cloture_en_attente_des_enfants=True)

    wake.process_wakes()

    assert [a for a, _ in reveils] == [ENFANT]
    assert "Mesure partielle : 3 jours sur 7" in reveils[0][1]


def _noeud(agent_id, parent="", interrompu=True):
    return {"agent_id": agent_id, "key": f"agent/{agent_id}", "parent": parent,
            "interrupted": interrompu, "kind": "work", "title": agent_id,
            "saved_at": datetime.now().isoformat(timespec="seconds")}


def test_un_sous_agent_arrete_sans_parent_capable_arrive_dans_la_boite(monkeypatch):
    noeuds = [_noeud("parent_mort"), _noeud("orphelin1", "parent_mort"),
              _noeud("parent_vivant", interrompu=False), _noeud("suivi", "parent_vivant"),
              _noeud("enfant_tui", "tui:abc"), _noeud("enfant_perdu", "purge0000000")]
    monkeypatch.setattr(fleet, "agent_tree", lambda avec_git=False: {"nodes": noeuds})

    cartes = {c["agent_id"]: c for c in inbox._conversations_arretees(set())}

    assert set(cartes) == {"parent_mort", "orphelin1", "enfant_tui", "enfant_perdu"}
    assert cartes["orphelin1"]["sous_agent"] is True
    assert "son parent ne peut plus" in cartes["orphelin1"]["raison"]
    assert cartes["parent_mort"]["sous_agent"] is False
