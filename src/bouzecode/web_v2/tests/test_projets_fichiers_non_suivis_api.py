# [desc] GET /api/projects/<slug>/fichiers-non-suivis (service de l'outil Projets, lecture pure) et passage Rundeck d'une tâche du Bureau : lien de l'exécution et fichiers refusés servis au front. [/desc]
from __future__ import annotations

import json
import subprocess

import pytest

from bouzecode.web_v2.services.work import micros, projects, taches_actions
from bouzecode.web_v2.tests import faux_rundeck_vm
from bouzecode.web_v2.tests.cli_tickets_aides import depot_demo
from bouzecode.web_v2.tests.test_rundeck_bout_en_bout import AGENT_VM, _script_vm
from bouzecode.web_v2.tests.test_v3_statut_des_taches import client  # noqa: F401


def test_les_fichiers_non_suivis_proposes_et_les_secrets_signales(tmp_path, client):  # noqa: F811
    racine = depot_demo(tmp_path)
    avant = subprocess.run(["git", "status", "--porcelain"], cwd=racine, capture_output=True,
                           text=True).stdout
    r = client.get("/api/projects/demo/fichiers-non-suivis?indices=plan")
    assert r.status_code == 200, r.get_data(as_text=True)
    corps = r.get_json()
    assert corps["proposes"] == ["notes/plan.md"] and corps["secrets_signales"] == [".env"]
    assert {f["chemin"] for f in corps["non_suivis"]} == {"notes/plan.md", ".env"}
    assert corps["git"]["branche"] == "main"
    assert subprocess.run(["git", "status", "--porcelain"], cwd=racine, capture_output=True,
                          text=True).stdout == avant  # lecture pure


def test_projet_inconnu_404_et_dossier_sans_git_409(tmp_path, client):  # noqa: F811
    r = client.get("/api/projects/absent/fichiers-non-suivis")
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "projet_inconnu"
    (tmp_path / "nu").mkdir()
    projects.PROJECTS_PATH.write_text(json.dumps([{"slug": "nu", "name": "nu",
                                                   "path": str(tmp_path / "nu")}]), encoding="utf-8")
    r = client.get("/api/projects/nu/fichiers-non-suivis")
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "pas_un_depot_git"


@pytest.fixture()
def rundeck(monkeypatch):
    etat, serveur = faux_rundeck_vm.demarrer(monkeypatch)
    yield etat
    serveur.shutdown()


def test_le_passage_rundeck_porte_son_lien_et_ses_fichiers_refuses(tmp_path, client, rundeck):  # noqa: F811
    depot_demo(tmp_path)
    micro = micros.create_micro(titre="ajouter b sur la vm", projet_slug="demo")
    r = client.post(f"/api/micros/{micro['id']}/lancer", json={"execution": {
        "cible": "rundeck", "projets": ["demo"], "mode": "agent",
        "commande": _script_vm(tmp_path, AGENT_VM), "fichiers_non_suivis": {"demo": [".env"]}}})
    assert r.status_code == 200, r.get_data(as_text=True)
    passage, = taches_actions.passages(micros.get_micro(micro["id"]))
    distant = passage["distant"]
    assert distant["execution_id"] == r.get_json()["distant"]["execution_id"]
    assert distant["url"].startswith("http://rundeck/execution/") and distant["mode"] == "agent"
    assert [f["chemin"] for f in distant["fichiers_refuses"]["demo"]] == [".env"]
