# [desc] Lots L3/L6 — critère §10 n° 10 sur les routes cibles (jamais 200 avec un échec), fin de run interne par jeton du run, crash démenti par le hook (L5), clôture forcée tracée à la réouverture. [/desc]
from __future__ import annotations

import pytest

from bouzecode.web_v2.services.work import cloture_ticket, ticket_fsm, tickets
from bouzecode.web_v2.services.work.fsm import etats

from aides_tickets import en_cours, fiche_agent
from delivery_repo import SLUG, client, develop_repo, project  # noqa: F401 — fixtures

URL = f"/api/projects/{SLUG}/tickets"


def test_archiver_puis_desarchiver_par_put_archived(client, project):
    ticket = tickets.create_ticket(SLUG, "rangé", "p")
    assert client.put(f"{URL}/{ticket['id']}/archived",
                      json={"archived": True}).get_json()["archived"] is True
    assert client.put(f"{URL}/{ticket['id']}/archived",
                      json={"archived": True}).get_json()["archived"] is True  # idempotent
    assert client.put(f"{URL}/{ticket['id']}/archived",
                      json={"archived": False}).get_json()["archived"] is False


def test_on_n_archive_pas_un_ticket_dont_l_agent_tourne(client, project):
    ticket = en_cours(SLUG, "agarchive01")
    reponse = client.put(f"{URL}/{ticket['id']}/archived", json={"archived": True})
    assert reponse.status_code == 409 and reponse.get_json()["error"]["code"] == "agent_actif"


ECHECS = [
    ("GET", "/api/projects/inconnu/tickets", None, 404),
    ("GET", f"{URL}/inconnu1", None, 404), ("GET", f"{URL}/inconnu1/events", None, 404),
    ("GET", f"{URL}/inconnu1/runs", None, 404), ("GET", f"{URL}/inconnu1/diff", None, 404),
    ("GET", "/api/projects/inconnu/occupation", None, 404),
    ("GET", "/api/agents/inconnu000000", None, 404),
    ("GET", "/api/agents/inconnu000000/children", None, 404),
    ("POST", f"{URL}/{{t}}/messages", {"text": "x"}, 409),
    ("POST", f"{URL}/{{t}}/messages", {}, 400),
    ("POST", f"{URL}/{{t}}/answer", {"text": "oui"}, 409),
    ("POST", f"{URL}/{{t}}/interrupt", None, 409),
    ("POST", f"{URL}/{{t}}/integrate", None, 409),
    ("POST", f"{URL}/{{t}}/harvest", None, 409),
    ("POST", f"{URL}/{{t}}/delivery/refresh", None, 409),
    ("POST", f"{URL}/{{t}}/close", {"outcome": "accepted"}, 409),
    ("POST", f"{URL}/{{t}}/close", {"outcome": "bof"}, 400),
    ("PUT", f"{URL}/{{t}}/archived", {}, 400),
    ("POST", f"{URL}/{{t}}/events", {"kind": "autre", "text": "x"}, 400),
    ("POST", "/api/agents/inconnu000000/messages", {"text": "x"}, 404),
    ("POST", "/api/agents/inconnu000000/stop", None, 404),
    ("POST", "/api/agents/inconnu000000/interruptions", None, 404),
    ("POST", "/internal/runs/inconnu000000/ended", {"close_reason": "final_answer"}, 404),
]


@pytest.mark.parametrize("methode, url, corps, attendu", ECHECS,
                         ids=[f"{m} {u} {s}" for m, u, _, s in ECHECS])
def test_aucune_route_cible_ne_rend_200_avec_un_echec(client, project, methode, url, corps,
                                                     attendu):
    ticket = tickets.create_ticket(SLUG, "nu", "rien")
    reponse = client.open(url.replace("{t}", ticket["id"]), method=methode, json=corps)
    assert reponse.status_code == attendu, reponse.get_data(as_text=True)[:300]
    erreur = reponse.get_json()["error"]
    assert erreur["code"] and erreur["message"] and "ok" not in reponse.get_json()


def test_la_fin_de_run_interne_exige_le_jeton_du_run(client, project):
    ticket = en_cours(SLUG, "agfin000001")
    fiche_agent("agfin000001", slug=SLUG, ticket_id=ticket["id"], run_token="secret-du-run")
    url = "/internal/runs/agfin000001/ended"

    sans = client.post(url, json={"close_reason": "final_answer"})
    faux = client.post(url, json={"close_reason": "final_answer"},
                       headers={"X-Bouzecode-Run-Token": "autre"})
    bon = client.post(url, json={"close_reason": "final_answer"},
                      headers={"X-Bouzecode-Run-Token": "secret-du-run"})

    assert sans.status_code == faux.status_code == 403
    assert sans.get_json()["error"]["code"] == "jeton_run_invalide"
    assert bon.status_code == 200 and bon.get_json()["state"] == etats.DELIVERED


def test_un_hook_tardif_dement_le_crash_constate_par_le_watchdog(client, project):
    """Limite L2 (a) : le watchdog a classé le run `stopped{crashed}` ; le hook de fin arrive
    ensuite et prouve une réponse finale → `delivered`, le `end` du run est corrigé."""
    ticket = en_cours(SLUG, "agcrash0001")
    fiche_agent("agcrash0001", slug=SLUG, ticket_id=ticket["id"], run_token="jeton1")
    ticket_fsm.appliquer(SLUG, ticket["id"], etats.CRASHED, "watchdog", code="crashed")

    reponse = client.post("/internal/runs/agcrash0001/ended", json={"close_reason": "final_answer"},
                          headers={"X-Bouzecode-Run-Token": "jeton1"})

    assert reponse.status_code == 200
    frais = tickets.get_ticket(SLUG, ticket["id"])
    assert frais["state"] == etats.DELIVERED
    assert frais["runs"][0]["end"]["delivered"] is True


def test_un_hook_tardif_sans_livraison_ne_corrige_rien(client, project):
    ticket = en_cours(SLUG, "agcrash0002")
    fiche_agent("agcrash0002", slug=SLUG, ticket_id=ticket["id"], run_token="jeton2")
    ticket_fsm.appliquer(SLUG, ticket["id"], etats.CRASHED, "watchdog", code="crashed")
    client.post("/internal/runs/agcrash0002/ended", json={"close_reason": "api_error"},
                headers={"X-Bouzecode-Run-Token": "jeton2"})
    assert tickets.get_ticket(SLUG, ticket["id"])["state"] == etats.STOPPED


def test_la_cloture_forcee_reste_au_journal_apres_reouverture(client, project, monkeypatch):
    """Limite L2 (b) : `cloture_forcee` est une raison d'état, donc effacée à la réouverture ;
    le journal, lui, garde la clôture forcée ET sa levée."""
    from bouzecode.web_v2.services.work import closure_guard
    ticket = en_cours(SLUG, "agforce0001")
    ticket_fsm.appliquer(SLUG, ticket["id"], etats.RUN_ENDED, delivered=True)
    monkeypatch.setattr(closure_guard, "force_closure", lambda slug, t: ["enfant1"])
    cloture_ticket.clore(SLUG, tickets.get_ticket(SLUG, ticket["id"]), "accepted")

    client.post(f"{URL}/{ticket['id']}/reopen")

    kinds = [e["kind"] for e in client.get(f"{URL}/{ticket['id']}/events").get_json()["events"]]
    assert "closure_forced" in kinds and "closure_forced_reopened" in kinds
    assert tickets.get_ticket(SLUG, ticket["id"])["state"] == etats.DELIVERED
