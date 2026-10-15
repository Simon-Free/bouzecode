# [desc] Tests that humans can create signalements via the API and that invalid severity or empty titles are rejected [/desc]
from __future__ import annotations

from bouzecode.web_v2.services.work import integration, micros, signalements, tickets
from bouzecode.web_v2.tests.test_brouillons_de_fusion_archives import _ticket_isole
from bouzecode.web_v2.tests.test_v3_statut_des_taches import SLUG, client  # noqa: F401 — fixture


def test_un_humain_emet_un_signalement(client):
    rep = client.post("/api/signalements", json={
        "gravite": "alerte", "titre": "La base de recette est lente",
        "detail": "mesuré 12 s par requête", "action_attendue": "relancer l'index"})
    assert rep.status_code == 201
    signalement = rep.get_json()["signalement"]
    assert signalement["gravite"] == "alerte"
    assert signalement["agent_id"] == "humain"
    assert signalements.get(signalement["id"])["titre"] == "La base de recette est lente"
    ouverts = client.get("/api/signalements").get_json()["items"]
    assert [s["id"] for s in ouverts] == [signalement["id"]]


def test_signalement_humain_invalide_refuse(client):
    assert client.post("/api/signalements", json={"gravite": "grave", "titre": "x"}).status_code == 400
    rep = client.post("/api/signalements", json={"gravite": "info", "titre": "  "})
    assert rep.status_code == 400
    assert rep.get_json()["error"]["code"] == "signalement_invalide" or "signalement_invalide" in rep.get_data(as_text=True)


def _tache_avec_passage(client, ticket) -> str:
    rep = client.post("/api/micros", json={"titre": "Scraper les énigmes"})
    assert rep.status_code == 201
    mid = rep.get_json()["micro"]["id"]
    micros.lier_ticket(mid, slug=SLUG, ticket_id=ticket["id"])
    return mid


def test_un_humain_demande_le_rollback_d_un_passage_integre(client, tmp_path):
    ticket = _ticket_isole(tmp_path)
    mid = _tache_avec_passage(client, ticket)
    assert integration.integrate_ticket(SLUG, ticket)["ok"] is True
    merge_commit = tickets.get_ticket(SLUG, ticket["id"])["integration"]["merge_commit"]
    assert merge_commit

    url = f"/api/micros/{mid}/passages/{ticket['id']}/revert"
    rep = client.post(url, json={"motif": "casse la recette"})
    assert rep.status_code == 201
    corps = rep.get_json()
    assert corps["merge_commit"] == merge_commit
    tache = micros.get_micro(corps["micro"]["id"])
    assert f"git revert -m 1 {merge_commit}" in tache["corps"]
    assert "casse la recette" in tache["corps"]

    encore = client.post(url, json={})
    assert encore.status_code == 200
    assert encore.get_json()["deja"] is True
    assert encore.get_json()["micro"]["id"] == tache["id"]


def test_rollback_refuse_un_passage_non_integre_ou_inconnu(client, tmp_path):
    ticket = _ticket_isole(tmp_path)
    mid = _tache_avec_passage(client, ticket)
    rep = client.post(f"/api/micros/{mid}/passages/{ticket['id']}/revert", json={})
    assert rep.status_code == 409
    assert "pas_integre" in rep.get_data(as_text=True)
    inconnu = client.post(f"/api/micros/{mid}/passages/deadbeef/revert", json={})
    assert inconnu.status_code == 404
