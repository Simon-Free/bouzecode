# [desc] Spec ticketing B6 / critère 10 : sur le périmètre tickets/flotte/agents/projets/micros, un échec n'est JAMAIS un 200 — code HTTP >= 400 et forme unique {"error": {"code", "message"}}. [/desc]
"""Test paramétré : chaque cas construit un échec réel (ticket inconnu, corps vide, rien à
intégrer, agent introuvable…) et vérifie la forme de la réponse. Aucun `ok: false` en 200,
aucun `error` en chaîne, aucun `routed: false`."""
from __future__ import annotations

import json
import subprocess

import pytest

from bouzecode.web_v2.services.work import projects, tickets

SLUG = "demo"


@pytest.fixture()
def client(tmp_path):
    depot = tmp_path / "depot"
    depot.mkdir()
    subprocess.run(["git", "init", "-q", str(depot)], check=True)
    projects.PROJECTS_PATH.write_text(
        json.dumps([{"slug": SLUG, "name": "Démo", "path": str(depot)}]), encoding="utf-8")
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def ticket_nu():
    """Un ticket sans worktree ni run : rien à intégrer, aucun agent à qui parler."""
    return tickets.create_ticket(SLUG, "nu", "rien")["id"]


T = f"/api/projects/{SLUG}/tickets"

CAS = [
    ("POST", "/api/projects/inconnu/tickets", {"title": "t", "prompt": "p"}, 404),
    ("POST", T, {}, 400),
    ("POST", f"{T}/inconnu1/integrate", None, 404),
    ("POST", f"{T}/{{ticket}}/integrate", None, 409),
    ("POST", f"{T}/{{ticket}}/messages", {}, 400),
    ("POST", f"{T}/{{ticket}}/messages", {"text": "go"}, 409),
    ("POST", f"{T}/inconnu1/messages", {"text": "x"}, 404),
    ("POST", f"{T}/{{ticket}}/events", {}, 400),
    ("POST", "/internal/runs/intrus000000/ended", {"close_reason": "final_answer"}, 404),
    ("PUT", f"{T}/inconnu1/archived", {"archived": True}, 404),
    ("POST", f"{T}/inconnu1/close", {"outcome": "accepted"}, 404),
    ("GET", f"{T}/inconnu1/diff", None, 404),
    ("POST", "/api/agents", {}, 400),
    ("POST", "/api/agents/inconnu000000/messages", {"text": "x"}, 404),
    ("POST", "/api/agents/inconnu000000/stop", None, 404),
    ("POST", "/api/agents/inconnu000000/interruptions", None, 404),
    ("DELETE", "/api/agents/inconnu000000/queue/q1", None, 404),
    ("POST", "/api/conversations/archive", {"keys": "pas une liste"}, 400),
    ("POST", "/api/projects", {}, 400),
    ("PATCH", "/api/projects/inconnu", {"description": "x"}, 404),
    ("DELETE", "/api/projects/inconnu", None, 404),
    ("POST", "/api/micros", {}, 400),
    ("POST", "/api/micros/inconnue/lancer", {}, 404),
    ("GET", "/api/lignes/inconnue", None, 404),
]


@pytest.mark.parametrize("methode,url,corps,attendu", CAS,
                         ids=[f"{m} {u} {s}" for m, u, _, s in CAS])
def test_un_echec_n_est_jamais_un_200(client, ticket_nu, methode, url, corps, attendu):
    url = url.replace("{ticket}", ticket_nu)
    if corps is not None:
        corps = {cle: (val.replace("{ticket}", ticket_nu) if isinstance(val, str) else val)
                 for cle, val in corps.items()}
    reponse = client.open(url, method=methode, json=corps)

    assert reponse.status_code == attendu, reponse.get_data(as_text=True)[:400]
    donnees = reponse.get_json()
    erreur = donnees.get("error")
    assert isinstance(erreur, dict), f"forme d'erreur unique attendue : {donnees}"
    assert erreur.get("code") and erreur.get("message"), donnees
    assert "ok" not in donnees and "routed" not in donnees, donnees


def test_un_commentaire_non_remis_est_conserve(client, ticket_nu):
    """Constat C7 : un envoi qui échoue ne perd pas le texte, il reste en commentaire."""
    reponse = client.post(f"{T}/{ticket_nu}/messages", json={"text": "à garder"})
    assert reponse.get_json()["error"]["details"]["commentaire_conserve"] is True
    textes = [c.get("text") for c in tickets.get_ticket(SLUG, ticket_nu).get("comments") or []]
    assert "à garder" in textes


def test_une_note_au_journal_n_est_pas_envoyee(client, ticket_nu):
    """POST …/events {kind: comment} est une NOTE au journal : rien ne part à l'agent."""
    reponse = client.post(f"{T}/{ticket_nu}/events", json={"kind": "comment", "text": "note"})
    assert reponse.status_code == 201 and reponse.get_json()["kind"] == "comment"
    notes = [(c["text"], c["sent"]) for c in tickets.get_ticket(SLUG, ticket_nu)["comments"]]
    assert notes == [("note", False)]


def test_creer_un_ticket_rend_201(client):
    reponse = client.post(f"/api/projects/{SLUG}/tickets",
                          json={"title": "t", "prompt": "p", "launch": False})
    assert reponse.status_code == 201 and reponse.get_json()["id"]


def test_diff_git_trop_lent_rend_504(client, tmp_path, monkeypatch):
    """Constat C13 : un timeout git est un 504 propre, pas un 500 (…/diff)."""
    from bouzecode.web_v2.services.work.api_tickets import livraison
    ticket = tickets.create_ticket(SLUG, "isolé", "p")
    tickets.poser(SLUG, ticket, worktree={"repo_root": str(tmp_path / "depot"), "base": "main",
                                          "branch": "agent/abc"})
    monkeypatch.setattr(livraison, "_GIT_TIMEOUT_S", 1e-9)
    reponse = client.get(f"{T}/{ticket['id']}/diff")
    assert reponse.status_code == 504
    assert reponse.get_json()["error"]["code"] == "git_trop_lent"


def test_diff_decrit_la_branche_du_ticket(client, tmp_path):
    """Constat C13 : un ticket isolé est décrit par SA branche, pas par le dépôt principal."""
    depot = tmp_path / "depot"
    git = ["git", "-C", str(depot), "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "base"], check=True)
    subprocess.run([*git, "branch", "-M", "main"], check=True)
    subprocess.run([*git, "checkout", "-q", "-b", "agent/abc"], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "travail du ticket"], check=True)
    subprocess.run([*git, "checkout", "-q", "main"], check=True)
    ticket = tickets.create_ticket(SLUG, "isolé", "p")
    ticket["worktree"] = {"branch": "agent/abc", "base": "main", "repo_root": str(depot)}
    tickets.update_ticket(SLUG, ticket)

    corps = client.get(f"{T}/{ticket['id']}/diff").get_json()

    assert (corps["branch"], corps["base"]) == ("agent/abc", "main")
    assert [c["subject"] for c in corps["commits"]] == ["travail du ticket"]
