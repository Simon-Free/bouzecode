# [desc] Concurrence (L2, critère 4, spec §9) : deux lancements simultanés → un seul passe, l'autre 409 `deja_actif` ; une écriture d'un instantané périmé → `version_obsolete` ; au plus un run vivant par ticket. [/desc]
from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.runtime.runner import agent_creation
from bouzecode.web_v2.services.work import projects, ticket_fsm, tickets
from bouzecode.web_v2.services.work.fsm import etats

SLUG = "p"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    chemin = tmp_path / "projects.json"
    monkeypatch.setattr(projects, "PROJECTS_PATH", chemin)
    chemin.write_text(json.dumps([{"slug": SLUG, "name": "p", "path": str(tmp_path)}]),
                      encoding="utf-8")
    from bouzecode.web_v2 import api_sanity, python_env_sanity
    monkeypatch.setattr(api_sanity, "require_api_sanity", lambda: None)
    monkeypatch.setattr(python_env_sanity, "require_python_env", lambda: None)
    app = create_app()
    app.config["TESTING"] = True
    return app


def _livre() -> dict:
    """Un ticket dont le premier agent a livré : relançable."""
    ticket = tickets.create_ticket(SLUG, "T", "faire")
    tickets.set_launching(SLUG, ticket)
    tickets.add_run(SLUG, ticket, "premier", "work", "m")
    return ticket_fsm.appliquer(SLUG, ticket["id"], etats.RUN_ENDED, delivered=True)


def test_deux_lancements_concurrents_un_seul_passe(client, monkeypatch):
    """Le premier lancement tient le ticket en `provisioning` pendant son spawn : le second,
    arrivé pendant ce temps, reçoit 409 `deja_actif` et rien ne démarre pour lui."""
    ticket = _livre()
    dans_le_spawn, liberer = threading.Event(), threading.Event()
    spawns: list[str] = []

    def spawn_lent(prompt, model, cwd, **kwargs):
        spawns.append(kwargs["ticket_id"])
        dans_le_spawn.set()
        assert liberer.wait(10)
        return SimpleNamespace(agent_id=f"relance{len(spawns)}")

    monkeypatch.setattr(agent_creation, "create_agent", spawn_lent)
    reponses: dict[str, object] = {}

    def lancer(nom: str) -> None:
        reponses[nom] = client.test_client().post(
            f"/api/projects/{SLUG}/tickets/{ticket['id']}/runs", json={"defer": False})

    premier = threading.Thread(target=lancer, args=("premier",))
    premier.start()
    assert dans_le_spawn.wait(10)
    lancer("second")  # pendant que le premier spawne
    liberer.set()
    premier.join(10)
    assert reponses["premier"].status_code == 202
    assert reponses["second"].status_code == 409
    erreur = reponses["second"].get_json()["error"]
    assert erreur["code"] == "deja_actif"
    assert erreur["details"]["state"] == etats.PROVISIONING
    assert len(spawns) == 1
    frais = tickets.get_ticket(SLUG, ticket["id"])
    assert frais["state"] == etats.RUNNING
    assert [r["agent_id"] for r in frais["runs"] if r["state"] != "ended"] == ["relance1"]


def test_lancements_concurrents_au_niveau_du_service():
    """N threads demandent le lancement du même ticket : exactement un obtient `provisioning`."""
    ticket = tickets.create_ticket(SLUG, "T", "faire")
    issues: list[str] = []
    barriere = threading.Barrier(6)

    def lancer() -> None:
        barriere.wait(10)
        try:
            tickets.set_launching(SLUG, {"id": ticket["id"]})
            issues.append("ok")
        except ticket_fsm.DejaActif:
            issues.append("deja_actif")

    fils = [threading.Thread(target=lancer) for _ in range(6)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(10)
    assert sorted(issues) == ["deja_actif"] * 5 + ["ok"]


def test_ecriture_d_un_instantane_perime_est_refusee():
    ticket = tickets.create_ticket(SLUG, "T", "faire")
    perime = tickets.get_ticket(SLUG, ticket["id"])
    tickets.poser(SLUG, {"id": ticket["id"]}, typology="manager")  # un autre écrivain passe
    perime["title"] = "écrasement"
    with pytest.raises(tickets.VersionObsolete) as exc:
        tickets.update_ticket(SLUG, perime)
    assert exc.value.details["state"] == etats.CREATED
    frais = tickets.get_ticket(SLUG, ticket["id"])
    assert frais["title"] == "T" and frais["typology"] == "manager"


def test_version_perimee_sur_une_route_donne_409_version_obsolete(client):
    ticket = _livre()
    version_lue = tickets.get_ticket(SLUG, ticket["id"])["version"]
    tickets.poser(SLUG, {"id": ticket["id"]}, typology="manager")
    reponse = client.test_client().post(f"/api/projects/{SLUG}/tickets/{ticket['id']}/close",
                                        json={"outcome": "accepted", "version": version_lue})
    assert reponse.status_code == 409
    assert reponse.get_json()["error"]["code"] == "version_obsolete"
    assert tickets.get_ticket(SLUG, ticket["id"])["state"] == etats.DELIVERED


def test_la_version_croit_a_chaque_ecriture():
    ticket = tickets.create_ticket(SLUG, "T", "faire")
    versions = [ticket["version"]]
    tickets.set_launching(SLUG, ticket)
    versions.append(ticket["version"])
    tickets.add_run(SLUG, ticket, "a1", "work", "m")
    versions.append(ticket["version"])
    assert versions == sorted(versions) and len(set(versions)) == 3


def test_un_run_neuf_clot_le_run_qu_il_remplace():
    """Invariant : un ticket `running` a exactement un run non terminé."""
    ticket = tickets.create_ticket(SLUG, "T", "faire")
    tickets.set_launching(SLUG, ticket)
    tickets.add_run(SLUG, ticket, "a1", "work", "m")
    tickets.add_run(SLUG, ticket, "a2", "work", "m")  # reprise par respawn
    frais = tickets.get_ticket(SLUG, ticket["id"])
    assert frais["state"] == etats.RUNNING
    assert [(r["agent_id"], r["state"]) for r in frais["runs"]] == [("a2", "running"),
                                                                    ("a1", "ended")]
    assert frais["runs"][1]["end"]["reason"] == "remplace"
