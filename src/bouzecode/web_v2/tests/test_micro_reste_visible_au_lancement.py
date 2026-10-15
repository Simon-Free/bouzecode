"""Lancer un agent sur une micro-tâche ne doit PAS la faire disparaître du Bureau.

Symptôme utilisateur (2026-09-09) : « je viens de lancer un ticket dans /bureau (une micro
tâche) et elle a disparu ». L'agent travaille, mais plus rien à l'écran ne dit qu'un travail
est en route : la ligne a été classée `faite` par le lancement lui-même, donc rendue
`archive` par la déduction de statut, donc sortie de la vue.

Le suivi d'une ligne lancée est déjà écrit (`statut_de` : `lancee` + tickets vivants =>
`en_cours`, agent fini => `inactif/a_relire` avec le rapport joint). Le lancement doit
S'ARRÊTER à `lancee` et laisser cet appareil faire son travail : la clôture d'une ligne
reste une réponse HUMAINE.

Garde-fou conservé : quand rien n'est parti (dépôt inconnu du registre), la ligne reste
elle aussi visible — c'était déjà le cas et ça ne doit pas régresser.
"""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import dispatch, projects

SLUG = "demo-application"


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def depot_ouvert(tmp_path):
    """Un dépôt ENREGISTRÉ (dossier non-git → isolation `shared`, aucun worktree créé)."""
    path = tmp_path / "demo_application"
    path.mkdir()
    entries = [{"slug": SLUG, "name": "demo_application", "path": str(path)}]
    projects.PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    projects.PROJECTS_PATH.write_text(json.dumps(entries), encoding="utf-8")
    return entries[0]


@pytest.fixture()
def sans_spawn(monkeypatch):
    """`dispatch()` part en `defer=True` : on neutralise `_launch_bg` (worktree + process)."""
    appels: list[tuple] = []

    def faux_launch_bg(*args, **kwargs):
        appels.append(args)

    monkeypatch.setattr(dispatch, "_launch_bg", faux_launch_bg)
    return appels


def _micro(client, titre, **body):
    response = client.post("/api/micros", json={"titre": titre, **body})
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["micro"]


def _lu(client, micro_id):
    response = client.get(f"/api/micros/{micro_id}")
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["micro"]


def _ligne_du_bureau(client, micro_id):
    """La ligne TELLE QUE L'ÉCRAN la reçoit : on la cherche dans toute la vue Bureau."""
    #  Liste COMPLÈTE : la liste par défaut est allégée (les `tickets` d'une ligne ne sont
    #  servis que pour une tâche dépliée, cf. `bureau_lignes.CHAMPS_DETAIL`).
    response = client.get("/api/lignes?complet=1")
    assert response.status_code == 200, response.get_data(as_text=True)
    vue = response.get_json()
    lignes = list(vue.get("non_rattachees") or [])
    for chantier in vue.get("chantiers") or []:
        lignes.extend(chantier.get("lignes") or [])
    for ligne in lignes:
        if ligne.get("id") == micro_id:
            return ligne
    return None


def test_une_micro_lancee_reste_dans_la_vue_bureau(client, depot_ouvert, sans_spawn):
    """Le geste réel de l'utilisateur : il lance, et il doit TOUJOURS voir sa ligne."""
    micro = _micro(client, "ne pas disparaitre au lancement", projet_slug=SLUG)

    lance = client.post(f"/api/micros/{micro['id']}/lancer", json={})
    assert lance.status_code == 200, lance.get_data(as_text=True)
    assert lance.get_json()["ticket_id"], "un dépôt enregistré doit produire un ticket"

    assert _lu(client, micro["id"])["etat"] == "lancee", (
        "le lancement s'arrête à `lancee` : classer la ligne est une réponse humaine")

    ligne = _ligne_du_bureau(client, micro["id"])
    assert ligne is not None, "la ligne lancée doit rester dans /api/lignes"
    assert ligne["statut"] != "archive", (
        "une ligne dont l'agent travaille encore n'est pas archivée : elle disparaîtrait")
    assert ligne["tickets"], "la ligne doit porter le ticket de l'agent lancé"


def test_un_lancement_qui_ne_part_pas_laisse_la_ligne_visible(client, sans_spawn):
    """Dépôt inconnu du registre : rien n'est parti, la ligne reste actionnable."""
    micro = _micro(client, "migrer demo_table", projet_slug="depot_inconnu_du_registre")

    lance = client.post(f"/api/micros/{micro['id']}/lancer", json={})
    #  SPEC v3 : le refus est une erreur HTTP (plus un 200 `ok:false` pris pour un succès),
    #  et la ligne RESTE brouillon — elle n'est plus marquée « lancée » à tort.
    assert lance.status_code == 400, lance.get_data(as_text=True)
    assert lance.get_json()["error"]["code"] == "depot_inconnu"

    assert _lu(client, micro["id"])["etat"] == "brouillon"
    ligne = _ligne_du_bureau(client, micro["id"])
    assert ligne is not None and ligne["statut"] != "archive"


def test_relancer_une_ligne_deja_lancee_reste_refuse(client, depot_ouvert, sans_spawn):
    """Le garde-fou anti double-lancement ne dépend plus du passage à `faite`."""
    micro = _micro(client, "pas deux agents sur la meme ligne", projet_slug=SLUG)

    premier = client.post(f"/api/micros/{micro['id']}/lancer", json={})
    assert premier.status_code == 200, premier.get_data(as_text=True)

    second = client.post(f"/api/micros/{micro['id']}/lancer", json={})
    assert second.status_code == 409, second.get_data(as_text=True)
    assert len(sans_spawn) == 1, "un seul agent doit être parti"
