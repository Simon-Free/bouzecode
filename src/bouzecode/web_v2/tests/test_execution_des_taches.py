# [desc] Lancement d'une tache avec `execution` (projets multi-depots, cible local|rundeck, fichiers non suivis) : validation, persistance tache + ticket, injection dans le prompt, contrat du lanceur distant. [/desc]
from __future__ import annotations

import json

import pytest

from bouzecode.backend.tools import bureau_tools
from bouzecode.web_v2.services.work import micros, projects, taches_execution
from bouzecode.web_v2.tests.test_v3_gestes_des_taches import (  # noqa: F401 — fixtures
    _ticket, client, sans_spawn,
)


@pytest.fixture()
def deux_depots(tmp_path):
    chemins = {slug: tmp_path / slug for slug in ("demo", "outils")}
    for chemin in chemins.values():
        chemin.mkdir()
    projects.PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    projects.PROJECTS_PATH.write_text(json.dumps(
        [{"slug": s, "name": s, "path": str(c)} for s, c in chemins.items()]), encoding="utf-8")
    return chemins


@pytest.fixture()
def outils_branches(client, monkeypatch):
    """Les outils de l'assistant parlent a la VRAIE app (client de test) au lieu du port 5056."""
    monkeypatch.setattr(bureau_tools, "_http", lambda m, chemin, corps=None:
                        client.open(chemin, method=m, json=corps).get_json())


def test_lancer_agent_multi_depots_persiste_et_injecte_l_execution(
        deux_depots, sans_spawn, outils_branches):
    rendu = bureau_tools.lancer_agent(
        prompt="Brancher le scraper sur la lib d'outils", project_slug="demo",
        projets=["outils"], fichiers_non_suivis={"outils": ["notes/plan.md"]})

    assert rendu["ok"] and rendu["execution"]["projets"] == ["demo", "outils"]
    _, ticket = _ticket(rendu["ticket_id"])
    assert ticket["execution"] == {"cible": "local", "projets": ["demo", "outils"],
                                   "fichiers_non_suivis": {"outils": ["notes/plan.md"]}}
    assert taches_execution.lire(rendu["tache_id"]) == ticket["execution"]
    for attendu in ("## Execution", "Cible : local.", "(depot principal)",
                    str(deux_depots["outils"] / "notes/plan.md")):
        assert attendu in ticket["prompt"], attendu
    assert len(sans_spawn) == 1


def test_rundeck_sans_lanceur_distant_est_refuse_et_rien_n_est_lance(
        client, deux_depots, sans_spawn, monkeypatch):
    monkeypatch.setattr(taches_execution, "MODULE_DISTANT", "module_rundeck_absent_xyz")
    micro = micros.create_micro(titre="job distant", projet_slug="demo")
    r = client.post(f"/api/micros/{micro['id']}/lancer",
                    json={"execution": {"cible": "rundeck"}})

    assert r.status_code == 501 and r.get_json()["error"]["code"] == "cible_indisponible"
    assert micros.get_micro(micro["id"])["etat"] == "brouillon"
    assert not sans_spawn


def test_rundeck_appelle_le_point_d_entree_avec_ticket_et_execution(
        client, deux_depots, sans_spawn, monkeypatch, tmp_path):
    """Un VRAI module distant (ecrit sur disque) remplace `bouzecode.remote` : le contrat est
    `lancer_sur_rundeck(ticket, execution) -> {ok, ...}`, aucun agent local n'est lance."""
    (tmp_path / "faux_lanceur_rundeck.py").write_text(
        "RECUS = []\n"
        "def lancer_sur_rundeck(ticket, execution):\n"
        "    RECUS.append((ticket, execution))\n"
        "    return {'ok': True, 'execution_id': '42', 'url': 'https://rundeck/42'}\n",
        encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(taches_execution, "MODULE_DISTANT", "faux_lanceur_rundeck")
    micro = micros.create_micro(titre="job distant", projet_slug="demo")
    r = client.post(f"/api/micros/{micro['id']}/lancer", json={
        "parent": "tui:abc", "execution": {"cible": "rundeck", "projets": ["demo"],
                                           "fichiers_non_suivis": {"demo": ["a.txt"]}}})

    assert r.status_code == 200, r.get_data(as_text=True)
    corps = r.get_json()
    assert corps["distant"]["execution_id"] == "42" and not sans_spawn
    import faux_lanceur_rundeck
    (ticket, execution), = faux_lanceur_rundeck.RECUS
    assert ticket["slug"] == "demo" and ticket["parent"] == "tui:abc"
    assert "## Execution" in ticket["prompt"] and execution["cible"] == "rundeck"
    # Sur la VM les chemins du poste n'existent pas : depot principal = repertoire courant.
    assert "- demo : . (depot principal)" in ticket["prompt"]
    assert "- a.txt" in ticket["prompt"] and str(deux_depots["demo"]) not in ticket["prompt"]
    assert micros.get_micro(micro["id"])["etat"] == "lancee"
    run, = _ticket(corps["ticket_id"])[1]["runs"]  # le run remote que le reveil suivra
    assert run["kind"] == "remote" and run["agent_id"] == "rd-42" and run["execution_id"] == "42"


@pytest.mark.parametrize("execution, code", [
    ({"cible": "lune"}, "cible_inconnue"),
    ({"projets": ["inconnu"]}, "depot_inconnu"),
    ({"fichiers_non_suivis": {"demo": ["../hors_du_depot.txt"]}}, "fichiers_invalides"),
    ({"fichiers_non_suivis": {"outils": ["x.md"]}}, "fichiers_invalides"),
    ({"mode": "tests", "commande": "tests/"}, "options_distantes"),
    ({"cible": "rundeck", "mode": "tests"}, "commande_manquante"),
    ({"cible": "rundeck", "mode": "lune", "commande": "x"}, "mode_inconnu"),
])
def test_execution_invalide_est_refusee(client, deux_depots, sans_spawn, execution, code):
    micro = micros.create_micro(titre="t", projet_slug="demo")
    r = client.post(f"/api/micros/{micro['id']}/lancer", json={"execution": execution})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == code
    assert not sans_spawn
