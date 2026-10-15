# [desc] La vision d'ensemble d'un chantier rendue à l'assistant du Bureau : provenance de chaque tâche (utilisateur, assistant, clôture de tel agent), livraisons, et signaux de ce qui est fait ailleurs ou en double — sur un chantier fabriqué comme celui du Portail des énigmes. [/desc]
"""On rejoue en petit le chantier réel du 2026-09-25 : une tâche principale livrée par un agent
qui a clos plusieurs fois (chaque clôture a ouvert ses suites, reformulées), un retour de test
envoyé ensuite, et un agent lancé hors tâche qui a ouvert « Corriger les points » et « Relire la
livraison » sur un travail que la tâche principale faisait déjà.

L'état est fabriqué par les vrais services (pont de clôture, retours, tickets) ; seules les
heures sont posées à la main, pour que « avant / après » ne dépende pas de l'horloge."""
from __future__ import annotations

import pytest

from bouzecode.backend.tools import bureau_tools
from bouzecode.web_v2.services.work import bilan_chantier, micros, runs_ticket, tickets
from bouzecode.web_v2.tests.aides_tickets import constater_tout
from bouzecode.web_v2.services.work.cloture_micros import ouvrir_micros_de_cloture
from bouzecode.web_v2.tests.test_v3_statut_des_taches import (  # noqa: F401
    SLUG, client, ecrire_agent,
)

AGENT_RACINE = "6bafe9cd5ee7"
AGENT_HORS_TACHE = "8789ff11400d"
LIVRAISON = {
    "answer": "Les 10 points sont corrigés.",
    "taches_terminees": ["5) Édition complète, persistance disque data/state.json + export"],
    "taches_restantes": [{"titre": "Écarts assumés sur Q25/Q26", "decision": True}],
}


def _dater(ids: list[str], at: str) -> None:
    """Pose l'heure d'une clôture sur ce qu'elle a ouvert (ligne, provenance, lien de suite)."""
    with micros._tx() as conn:
        for ident in ids:
            conn.execute("UPDATE micros SET created_at = ? WHERE id = ?", (at, ident))
            conn.execute("UPDATE micro_provenance SET at = ? WHERE micro_id = ?", (at, ident))
            conn.execute("UPDATE micro_suites SET at = ? WHERE micro_id = ?", (at, ident))


def _cloture(restes: list, ticket_id: str, session: str, at: str) -> list[str]:
    creees = ouvrir_micros_de_cloture(restes, ticket_id=ticket_id, slug=SLUG, session_id=session)
    ids = [m["id"] for m in creees]
    _dater(ids, at)
    return ids


@pytest.fixture()
def chantier(monkeypatch):
    """Le chantier « Portail des énigmes », tel qu'il était avant le point demandé."""
    macro = micros.ensure_macro("Portail des énigmes")
    principale = micros.create_micro(titre="Scraper les énigmes, interface Tinder",
                                     macro_id=macro["id"], origine="assistant")
    ticket = tickets.create_ticket(SLUG, principale["titre"], principale["titre"])
    with monkeypatch.context() as horloge:
        horloge.setattr(runs_ticket, "_now", lambda: "2026-09-24T23:18:54")
        tickets.add_run(SLUG, ticket, AGENT_RACINE, "work", "m")
    micros.lier_ticket(principale["id"], slug=SLUG, ticket_id=ticket["id"])
    with micros._tx() as conn:
        conn.execute("UPDATE micro_tickets SET at = '2026-09-24T23:18:54'")
    micros.marquer_etat(principale["id"], "lancee")
    ecrire_agent(AGENT_RACINE, final=LIVRAISON, ticket_id=ticket["id"])
    constater_tout()  # lot L2 : la livraison est constatée par le watchdog
    session = "260042cc"
    brancher, exporter = _cloture(
        [{"titre": "Brancher d'autres sites sources que le Kangourou"},
         {"titre": "Exporter les verdicts (localStorage seulement)"}],
        ticket["id"], session, "2026-09-24T23:42:27")
    [etendre] = _cloture([{"titre": "Étendre le scraping à d'autres sites"}],
                         ticket["id"], session, "2026-09-25T00:01:08")
    retour = micros.add_retour(principale["id"], "Retours de test : corrige les 10 points",
                               ticket_id=ticket["id"], mode="continuer")
    with micros._tx() as conn:
        conn.execute("UPDATE micro_retours SET created_at = '2026-09-25T01:05:12' WHERE id = ?",
                     (retour["id"],))
    hors_tache = tickets.create_ticket(SLUG, "J'ai testé le portail livré", "J'ai testé…")
    tickets.add_run(SLUG, hors_tache, AGENT_HORS_TACHE, "work", "m")
    corriger, relire = _cloture(
        [{"titre": "Corriger les 10 points du portail",
          "corps": f"En cours chez l'agent {AGENT_RACINE} (tâche {principale['id']})."},
         {"titre": "Relire la livraison de l'agent sur les 10 retours",
          "corps": f"Tâche {principale['id']} : à vérifier à la livraison."}],
        hors_tache["id"], "eee47bbd", "2026-09-25T01:05:52")
    for ident in (corriger, relire):
        micros.update_micro(ident, macro_id=macro["id"])
    [ecarts] = _cloture(LIVRAISON["taches_restantes"], ticket["id"], session, "2026-09-25T02:41:42")
    a_la_main = micros.create_micro(titre="Ajouter un mode sombre", macro_id=macro["id"])
    return dict(macro=macro, principale=principale["id"], ticket=ticket["id"], brancher=brancher,
                exporter=exporter, etendre=etendre, corriger=corriger, relire=relire,
                ecarts=ecarts, a_la_main=a_la_main["id"], hors_tache=hors_tache["id"])


def _bloc(texte: str, ident: str) -> str:
    """Le bloc d'une tâche : de sa ligne « ▸ id » à la suivante."""
    debut = texte.index(f"▸ {ident}")
    suite = texte.find("\n▸ ", debut + 1)
    fin = texte.find("\n\nRAPPROCHEMENTS", debut)
    bornes = [b for b in (suite, fin) if b != -1]
    return texte[debut: min(bornes) if bornes else len(texte)]


def test_chaque_tache_dit_qui_l_a_creee_et_quand(chantier):
    texte = bilan_chantier.vue_ensemble("Portail des énigmes")["texte"]

    assert "créée 24/09 23:42 par la clôture de l'agent 6bafe9cd (ticket " \
        f"{chantier['ticket']}, passage de la tâche {chantier['principale']}" \
        in _bloc(texte, chantier["brancher"])
    assert "session 260042cc" in _bloc(texte, chantier["brancher"])
    assert "lancé hors tâche : « J'ai testé le portail livré »" in _bloc(texte, chantier["corriger"])
    assert "par l'utilisateur" in _bloc(texte, chantier["a_la_main"])
    assert "par l'assistant" in _bloc(texte, chantier["principale"])


def test_la_livraison_montre_ce_qui_a_ete_fait_et_les_suites_ouvertes(chantier):
    bloc = _bloc(bilan_chantier.vue_ensemble("Portail des énigmes")["texte"], chantier["principale"])

    assert "À vérifier" in bloc
    assert "fait : 5) Édition complète, persistance disque data/state.json + export" in bloc
    assert "à décider : Écarts assumés sur Q25/Q26" in bloc
    assert f"suites ouvertes par ce passage : {chantier['ecarts']}" in bloc
    assert "retour envoyé 25/09 01:05 : Retours de test" in bloc


def test_une_suite_d_une_tache_reprise_depuis_est_signalee(chantier):
    texte = bilan_chantier.vue_ensemble("Portail des énigmes")["texte"]

    exporter = _bloc(texte, chantier["exporter"])
    assert f"⚑ est une suite de la tâche {chantier['principale']}" in exporter
    assert "retour envoyé 25/09 01:05" in exporter
    assert "clôturée de nouveau 25/09 00:01, 25/09 02:41" in exporter
    corriger = _bloc(texte, chantier["corriger"])
    assert f"⚑ cite la tâche {chantier['principale']}" in corriger
    assert "clôturée de nouveau 25/09 02:41" in corriger
    assert "⚑" not in _bloc(texte, chantier["ecarts"]), "rien n'a suivi la dernière clôture"


def test_une_relecture_qui_double_la_carte_a_verifier_est_signalee(chantier):
    bloc = _bloc(bilan_chantier.vue_ensemble("Portail des énigmes")["texte"], chantier["relire"])

    assert "attend déjà ta vérification (À vérifier) : probable doublon de cette carte" in bloc


def test_les_rapprochements_nomment_les_doublons_et_les_clotures_repetees(chantier):
    texte = bilan_chantier.vue_ensemble("Portail des énigmes")["texte"]
    rapprochements = texte[texte.index("RAPPROCHEMENTS"):]

    assert f"≈ {chantier['brancher']} « Brancher d'autres sites" in rapprochements
    assert f"/ {chantier['etendre']} « Étendre le scraping" in rapprochements
    assert "session 260042cc : suites ouvertes à 3 clôtures" in rapprochements


def test_une_tache_classee_apparait_dans_les_archivees_avec_son_commentaire(client, chantier):
    client.post(f"/api/micros/{chantier['corriger']}/classer",
                json={"motif": "faite", "de": chantier["principale"], "auteur": "assistant",
                      "commentaire": "fait au tour de retours"})

    texte = bilan_chantier.vue_ensemble(chantier["macro"]["id"])["texte"]

    archivees = texte[texte.index("ARCHIVÉES"):]
    assert f"{chantier['corriger']} « Corriger les 10 points du portail » — Faite : Faite par" \
        in archivees
    assert "fait au tour de retours (commentaire de l'assistant" in archivees
    assert f"▸ {chantier['corriger']}" not in texte


def test_un_chantier_inconnu_rend_la_liste_des_chantiers(chantier):
    rendu = bilan_chantier.vue_ensemble("Chantier qui n'existe pas")

    assert rendu["ok"] is False and rendu["erreur"] == "chantier_inconnu"
    assert {"id": chantier["macro"]["id"], "titre": "Portail des énigmes"} in rendu["chantiers"]


def test_l_outil_de_l_assistant_rend_la_vue_d_ensemble(chantier):
    rendu = bureau_tools.taches(action="vue_ensemble", chantier="portail enigmes")
    sans_chantier = bureau_tools.taches(action="vue_ensemble")

    assert rendu["ok"] and rendu["chantier"]["id"] == chantier["macro"]["id"]
    assert rendu["texte"].startswith("CHANTIER ")
    assert len(rendu["texte"]) < 12000, "raisonnable en jetons"
    assert sans_chantier["erreur"] == "chantier_requis"

