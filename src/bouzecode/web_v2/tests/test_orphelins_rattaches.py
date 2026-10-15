# [desc] Tâches orphelines : les suites de clôture d'un sous-agent héritent du chantier de la tâche de leur ancêtre, et les orphelines déjà créées y sont rattachées une fois (avec trace). [/desc]
"""Un sous-agent n'a pas de tâche du Bureau : c'est son ANCÊTRE qui en a une.

Cas réel (essai du 2026-09-25, ~/bouzecode-essai) : la tâche « Scraper les énigmes… » (chantier
« Portail des énigmes ») a lancé l'agent 6bafe9cd, qui a délégué les tickets a139daa2 et
0f852f4d. Leurs clôtures ont ouvert 5 tâches — toutes « Sans chantier », parce que la remontée
ticket → chantier ne regardait que le ticket lui-même (`micro_tickets`), pas son parent.

Tout passe par les vrais services et la vraie base isolée. Aucun mock.
"""
from bouzecode.web_v2.services.work import micros, orphelins, tickets
from bouzecode.web_v2.services.work.cloture_micros import ouvrir_micros_de_cloture


def _famille():
    """Tâche → ticket de6724a5 (agent 6bafe9cd) → enfant a139daa2 (agent 40ea29e4) → petit-enfant."""
    macro = micros.ensure_macro("Portail des énigmes")
    mere = micros.create_micro(titre="Scraper les énigmes", macro_id=macro["id"])
    micros.lier_ticket(mere["id"], slug="portail-enigmes", ticket_id="de6724a5")
    tickets.update_ticket("portail-enigmes", {"id": "de6724a5", "parent": "dispatcher:manual",
                                              "runs": [{"agent_id": "6bafe9cd5ee7", "kind": "work"}]})
    tickets.update_ticket("portail-enigmes", {"id": "a139daa2", "parent": "6bafe9cd5ee7",
                                              "runs": [{"agent_id": "40ea29e4253a", "kind": "work"}]})
    tickets.update_ticket("portail-enigmes", {"id": "e7ca0970", "parent": "40ea29e4253a",
                                              "runs": [{"agent_id": "85ce949a46cc", "kind": "work"}]})
    return macro


def test_le_chantier_se_herite_de_l_ancetre():
    macro = _famille()
    assert micros.macro_du_ticket("a139daa2") == macro["id"]
    assert micros.macro_du_ticket("e7ca0970") == macro["id"]


def test_un_parent_sans_tache_ne_rattache_rien():
    tickets.update_ticket("p", {"id": "seul", "parent": "agent-inconnu", "runs": []})
    tickets.update_ticket("p", {"id": "boucle", "parent": "ag-b", "runs": [{"agent_id": "ag-b"}]})
    assert micros.macro_du_ticket("seul") == ""
    assert micros.macro_du_ticket("boucle") == ""


def test_les_suites_d_un_sous_agent_vont_dans_le_chantier_de_l_ancetre():
    macro = _famille()
    [suite] = ouvrir_micros_de_cloture(["Régénérer data/enigmes.json par le réseau"],
                                       ticket_id="a139daa2", slug="portail-enigmes")
    assert suite["macro_id"] == macro["id"]


def _orpheline_d_avant_le_correctif(titre, ticket_id):
    """Ce que l'ancien pont a laissé en base : une suite « Sans chantier », liée à son ticket."""
    from bouzecode.web_v2.services.work import suites_cloture
    micro = micros.create_micro(titre=titre, origine="cloture_agent", projet_slug="portail-enigmes")
    suites_cloture.lier(ticket_id, titre, micro["id"], "creee")
    return micro


def test_les_orphelines_existantes_sont_rattachees_une_fois_avec_trace():
    macro = _famille()
    orpheline = _orpheline_d_avant_le_correctif("Produire une figure Écoliers 2024", "a139daa2")
    humaine = micros.create_micro(titre="Idée en vrac")  # jamais issue d'une clôture

    assert orphelins.balayer() == [orpheline["id"]]

    relue = micros.get_micro(orpheline["id"])
    assert relue["macro_id"] == macro["id"]
    assert "Portail des énigmes" in relue["precisions"][-1]["texte"]
    assert micros.get_micro(humaine["id"])["macro_id"] == ""
    #  L'utilisateur la remet « Sans chantier » : le balayage suivant ne la reprend pas.
    micros.update_micro(orpheline["id"], macro_id="")
    assert orphelins.balayer() == []
    assert micros.get_micro(orpheline["id"])["macro_id"] == ""
