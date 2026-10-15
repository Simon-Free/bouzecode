# [desc] Tache lancee sur Rundeck de bout en bout (faux Rundeck + faux share, paquet joue par vm_runner) : run remote, suivi a cadence bornee, recuperation, branche agent/<ticket> importee, parent reveille ; echec = crash + signalement. [/desc]
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from bouzecode.backend.tools import bureau_tools
from bouzecode.web_v2.runtime.runner import agent_fiche, agent_registre
from bouzecode.web_v2.services.work import fleet, micros, projects, signalements, tickets, wake
from bouzecode.web_v2.services.work.distant import suivi
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests import faux_rundeck_vm
from bouzecode.web_v2.tests.test_v3_statut_des_taches import client, ecrire_agent  # noqa: F401
from bouzecode.web_v2.runtime.runner import agent_reprise

PARENT = "parentrd0001"


def _git(depot, *arguments):
    return subprocess.run(["git", *arguments], cwd=depot, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture()
def depot(tmp_path):
    chemin = tmp_path / "demo"
    chemin.mkdir()
    _git(chemin, "init", "-q", "-b", "main")
    _git(chemin, "config", "user.email", "t@example.invalid")
    _git(chemin, "config", "user.name", "T")
    (chemin / "a.txt").write_text("a\n", encoding="utf-8")
    _git(chemin, "add", "a.txt")
    _git(chemin, "commit", "-q", "-m", "initial")
    (chemin / ".env").write_text("SECRET=1\n", encoding="utf-8")
    projects.PROJECTS_PATH.write_text(json.dumps([{"slug": "demo", "name": "demo",
                                                   "path": str(chemin)}]), encoding="utf-8")
    return chemin


@pytest.fixture()
def rundeck(monkeypatch):
    etat, serveur = faux_rundeck_vm.demarrer(monkeypatch)
    yield etat
    serveur.shutdown()


@pytest.fixture()
def horloge(monkeypatch):
    instant = [1000.0]
    monkeypatch.setattr(suivi, "HORLOGE", lambda: instant[0])
    suivi.oublier_cadence()
    return instant


@pytest.fixture()
def reveils(monkeypatch, tmp_path):
    """Le parent (manager clos, process fini) existe ; chaque reveil est note au lieu de lancer."""
    ecrire_agent(PARENT)
    fiche = agent_fiche.AGENTS_DIR / f"{PARENT}.json"
    fiche.write_text(json.dumps({**json.loads(fiche.read_text(encoding="utf-8")),
                                 "cwd": str(tmp_path)}), encoding="utf-8")
    agent_registre._agent_file_cache.clear()
    monkeypatch.setattr(wake, "WAKE_STATE_PATH", tmp_path / "wake_state.json")
    notes: list[tuple[str, str]] = []
    monkeypatch.setattr(agent_reprise, "continue_agent",
                        lambda agent, message: notes.append((agent.agent_id, message)) or agent)
    return notes


def _script_vm(tmp_path, code: str) -> str:
    chemin = tmp_path / "script_vm.py"
    chemin.write_text(code, encoding="utf-8")
    return f'"{sys.executable}" "{chemin}"'


AGENT_VM = (
    "import os, pathlib, subprocess\n"
    "pathlib.Path('b.txt').write_text('ecrit sur la vm\\n')\n"
    "subprocess.run(['git', 'add', 'b.txt'], check=True)\n"
    "subprocess.run(['git', 'commit', '-q', '-m', 'vm: ajoute b'], check=True)\n"
    "pathlib.Path(os.environ['BZ_RESULTAT'], 'reponse.md').write_text("
    "'Rapport distant : b.txt ajoute.\\nVERDICT: OK')\n"
    # la fiche que `bouzecode -p --result-file` ecrit apres un FinalAnswer : sans elle, rien ne
    # prouve la livraison (seul FinalAnswer livre)
    "pathlib.Path(os.environ['BZ_RESULTAT'], 'reponse.cloture.json').write_text("
    "'{\"close_reason\": \"final_answer\", \"final_answer\": true}')\n")


def _lancer(client, commande: str) -> dict:  # noqa: F811
    micro = micros.create_micro(titre="ajouter b sur la vm", projet_slug="demo")
    r = client.post(f"/api/micros/{micro['id']}/lancer", json={
        "parent": PARENT, "execution": {"cible": "rundeck", "projets": ["demo"], "mode": "agent",
                                        "commande": commande,
                                        "fichiers_non_suivis": {"demo": [".env"]}}})
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _ticket(ticket_id: str) -> dict:
    return tickets.get_ticket("demo", ticket_id)


def test_agent_sur_rundeck_livre_sa_branche_et_reveille_le_parent(
        client, depot, rundeck, horloge, reveils, tmp_path):  # noqa: F811
    corps = _lancer(client, _script_vm(tmp_path, AGENT_VM))
    ticket_id = corps["ticket_id"]

    distant = corps["distant"]
    assert distant["ok"] and distant["execution_id"] == "100" and distant["run_id"]
    assert ".env" in json.dumps(distant["fichiers_refuses"]["demo"])
    run, = _ticket(ticket_id)["runs"]
    assert run["kind"] == "remote" and run["agent_id"] == f"rd-{distant['run_id']}"
    assert run["execution_id"] == "100" and run["url"] and run["started_at"]

    wake.tick()  # 1re lecture : Rundeck repond « running »
    ticket = _ticket(ticket_id)
    assert ticket["state"] == etats.RUNNING
    assert tickets.derive_status(ticket) == "en cours" and reveils == []
    noeud, = [n for n in fleet.habiller({"nodes": []})["nodes"] if n["key"] == f"remote/{ticket_id}"]
    assert noeud["liveness"] == "running" and noeud["parent"] == PARENT

    wake.tick()  # 8 s plus tard : PAS de nouvelle lecture de Rundeck (cadence >= 30 s)
    assert rundeck.lectures_etat == 1
    horloge[0] += suivi.CADENCE_S + 1
    wake.tick()  # issue : suivre -> recuperer -> run clos -> reveil

    run, = _ticket(ticket_id)["runs"]
    assert run["termine"] and run["issue"] == "livre" and run["completed"] and run["turns"] == 1
    assert run["branches"]["demo"]["branche"] == f"agent/{ticket_id}"
    assert _git(depot, "show", f"agent/{ticket_id}:b.txt") == "ecrit sur la vm"
    assert _git(depot, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert not any("/resultat/" in c or "/paquet/" in c for c in rundeck.fichiers)  # share nettoye
    assert _ticket(ticket_id)["state"] == etats.DELIVERED
    (parent, digest), = reveils
    assert parent == PARENT and ticket_id in digest
    assert "Rapport distant : b.txt ajoute." in digest and "VERDICT: OK" in digest
    assert f"agent/{ticket_id}" in digest

    wake.tick()
    horloge[0] += suivi.CADENCE_S + 1
    wake.tick()
    assert len(reveils) == 1  # run clos : plus suivi, parent pas re-reveille


def test_vm_en_panne_plante_le_ticket_signale_et_reveille_le_parent(
        client, depot, rundeck, horloge, reveils, tmp_path):  # noqa: F811
    rundeck.panne = True
    ticket_id = _lancer(client, _script_vm(tmp_path, AGENT_VM))["ticket_id"]

    wake.tick()
    horloge[0] += suivi.CADENCE_S + 1
    wake.tick()

    ticket = _ticket(ticket_id)
    run, = ticket["runs"]
    assert ticket["state"] == etats.STOPPED and run["issue"] == "echec" and not run.get("completed")
    assert "n'a pas abouti" in run["raison"]
    assert ticket["state_reason"]["code"] == "crashed"
    signalement, = [s for s in signalements.ouverts() if s["ticket_id"] == ticket_id]
    assert signalement["gravite"] == "alerte" and signalement["parents"] == [PARENT]
    assert signalement["agent_id"] == run["agent_id"]
    (_, digest), = reveils
    assert "CRASHED" in digest and "n'a pas abouti" in digest and "LIVRAISON" not in digest
    assert "Execution Rundeck en echec" in digest  # le signalement arrive avec le reveil


def test_tests_sur_rundeck_par_l_outil_de_l_assistant(
        client, depot, rundeck, horloge, reveils, tmp_path, monkeypatch):  # noqa: F811
    """`LancerAgent(cible='rundeck', mode_distant='tests')` : la VM joue pytest, les tests rouges
    sont un RESULTAT livre (pas un crash), les fichiers refuses sont dits a l'assistant."""
    monkeypatch.setattr(bureau_tools, "_http", lambda m, chemin, corps=None:
                        client.open(chemin, method=m, json=corps).get_json())
    monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", str(tmp_path / f"{PARENT}.ipc"))
    rundeck.commande_vm = _script_vm(tmp_path, (
        "import os, pathlib, sys\n"
        "pathlib.Path(os.environ['BZ_RESULTAT'], 'junit.xml').write_text("
        "'<testsuite tests=\"3\" failures=\"1\" errors=\"0\" skipped=\"0\"/>')\n"
        "print('1 failed, 2 passed')\nsys.exit(1)\n"))

    lance = bureau_tools.lancer_agent(
        prompt="Jouer les tests web sous Linux", project_slug="demo", cible="rundeck",
        mode_distant="tests", commande_tests="tests/web -m playwright", navigateur=False,
        fichiers_non_suivis={"demo": [".env"]})

    assert lance["ok"] and lance["distant"]["execution_id"] == "100", lance
    assert "FICHIERS REFUSES" in lance["consigne_distant"] and ".env" in lance["consigne_distant"]
    commande = rundeck.manifestes[0]["commande"]
    assert "python -m pytest tests/web -m playwright" in commande and "--junitxml" in commande
    wake.tick()
    horloge[0] += suivi.CADENCE_S + 1
    wake.tick()

    run, = _ticket(lance["ticket_id"])["runs"]
    assert run["issue"] == "livre" and run["code"] == 1 and run["mode"] == "tests"
    (parent, digest), = reveils
    assert parent == PARENT and "tests ROUGES" in digest
    assert "3 tests, 1 en echec" in digest and "1 failed, 2 passed" in digest
