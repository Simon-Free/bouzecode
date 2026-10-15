# [desc] Tache Rundeck via clone GitLab + worktree (faux Rundeck/share, « GitLab » = depot nu local) : bundle incremental, retour en worktree local, `integrate` 202 -> closed, conflit -> conflict, multi-projets. [/desc]
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bouzecode.web_v2.services.work import micros, projects, tickets, wake
from bouzecode.web_v2.services.work.distant import suivi
from bouzecode.web_v2.tests import faux_rundeck_vm
from bouzecode.web_v2.tests.test_v3_statut_des_taches import client  # noqa: F401


def _git(depot, *arguments):
    return subprocess.run(["git", *arguments], cwd=depot, check=True, capture_output=True,
                          text=True).stdout.strip()


def _commit(depot: Path, chemin: str, contenu: str, message: str) -> None:
    (depot / chemin).write_text(contenu, encoding="utf-8")
    _git(depot, "add", chemin)
    _git(depot, "commit", "-q", "-m", message)


def _depot_avec_gitlab(racine: Path, nom: str) -> Path:
    """Un depot local clone d'un « GitLab » (depot nu), avec un commit pousse et un NON pousse."""
    gitlab = racine / "gitlab" / f"{nom}.git"
    gitlab.mkdir(parents=True)
    _git(gitlab, "init", "-q", "--bare", "-b", "main")
    local = racine / nom
    _git(racine, "clone", "-q", str(gitlab), str(local))
    for cle, valeur in (("user.email", "t@example.invalid"), ("user.name", "T"), ("core.autocrlf", "false")):
        _git(local, "config", cle, valeur)
    _commit(local, "a.txt", "a\n", "pousse")
    _git(local, "push", "-q", "origin", "main")
    _commit(local, "local.txt", "non pousse\n", "non pousse")
    return local


@pytest.fixture()
def depots(tmp_path, monkeypatch):
    monkeypatch.setenv("BZ_CACHE_DEPOTS", str(tmp_path / "cache_vm"))
    monkeypatch.setenv("GITLAB_TOKEN", "jeton-gitlab-de-test")  # active la source GitLab
    chemins = {nom: _depot_avec_gitlab(tmp_path, nom) for nom in ("demo", "outils")}
    projects.PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    projects.PROJECTS_PATH.write_text(json.dumps(
        [{"slug": s, "name": s, "path": str(c)} for s, c in chemins.items()]), encoding="utf-8")
    return chemins


@pytest.fixture()
def rundeck(monkeypatch):
    etat, serveur = faux_rundeck_vm.demarrer(monkeypatch)
    yield etat
    serveur.shutdown()


AGENT = ("import pathlib, subprocess\n"
         "assert pathlib.Path('local.txt').read_text() == 'non pousse\\n'  # commit non pousse present\n"
         "pathlib.Path('a.txt').write_text('a par l agent\\n')\n"
         "subprocess.run(['git', 'commit', '-qam', 'agent: a'], check=True)\n"
         "for depot in SECONDAIRES:\n"
         "    pathlib.Path('..', depot, 'b.txt').write_text('b\\n')\n"
         "    subprocess.run(['git', 'add', 'b.txt'], cwd=f'../{depot}', check=True)\n"
         "    subprocess.run(['git', 'commit', '-qm', 'agent: b'], cwd=f'../{depot}', check=True)\n"
         "import os\n"  # fiche ecrite par `bouzecode -p --result-file` apres FinalAnswer (seule fin qui livre)
         "pathlib.Path(os.environ['BZ_RESULTAT'], 'reponse.cloture.json').write_text("
         "'{\"close_reason\": \"final_answer\", \"final_answer\": true}')\n")


def _livrer(client, tmp_path, projets: list[str]) -> str:  # noqa: F811
    script = tmp_path / "agent_vm.py"
    script.write_text(f"SECONDAIRES = {projets[1:]!r}\n" + AGENT, encoding="utf-8")
    micro = micros.create_micro(titre="modifier a sur la vm", projet_slug="demo")
    r = client.post(f"/api/micros/{micro['id']}/lancer", json={"execution": {
        "cible": "rundeck", "projets": projets, "mode": "agent",
        "commande": f'"{sys.executable}" "{script}"'}})
    assert r.status_code == 200, r.get_data(as_text=True)
    corps = r.get_json()
    for _ in range(2):  # running, puis issue (cadence du suivi neutralisee)
        suivi.oublier_cadence()
        wake.tick()
    return corps


def test_clone_gitlab_puis_worktree_local_et_integrate_clot_le_ticket(client, depots, rundeck, tmp_path):  # noqa: F811
    corps = _livrer(client, tmp_path, ["demo"])
    ticket = tickets.get_ticket("demo", corps["ticket_id"])

    transfert = corps["distant"]["transfert"]["demo"]
    assert transfert["source"] == "remote" and transfert["commits_a_envoyer"] == 1
    assert ticket["state"] == "delivered", ticket.get("state_reason")
    meta = ticket["worktree"]
    assert meta["branch"] == f"agent/{ticket['id']}" and meta["base"] == "main" and Path(meta["worktree"]).is_dir()
    assert Path(meta["worktree"], "a.txt").read_text(encoding="utf-8") == "a par l agent\n"

    r = client.post(f"/api/projects/demo/tickets/{ticket['id']}/integrate", json={"wait": True})

    assert r.status_code == 202, r.get_data(as_text=True)
    assert tickets.get_ticket("demo", ticket["id"])["state"] == "closed"
    assert _git(depots["demo"], "show", "main:a.txt") == "a par l agent"


def test_conflit_a_l_integration_donne_conflict(client, depots, rundeck, tmp_path):  # noqa: F811
    ticket_id = _livrer(client, tmp_path, ["demo"])["ticket_id"]
    _commit(depots["demo"], "a.txt", "a par l humain\n", "humain: a")  # la base bouge entre-temps

    client.post(f"/api/projects/demo/tickets/{ticket_id}/integrate", json={"wait": True})

    ticket = tickets.get_ticket("demo", ticket_id)
    assert ticket["state"] == "conflict" and "a.txt" in json.dumps(ticket.get("integration") or ticket)


def test_multi_projets_chaque_depot_a_sa_branche_et_son_worktree(client, depots, rundeck, tmp_path):  # noqa: F811
    ticket_id = _livrer(client, tmp_path, ["demo", "outils"])["ticket_id"]
    ticket = tickets.get_ticket("demo", ticket_id)

    secondaire, = ticket["worktrees_secondaires"]
    assert secondaire["projet"] == "outils" and secondaire["branch"] == f"agent/{ticket_id}"
    assert Path(secondaire["worktree"], "b.txt").read_text(encoding="utf-8") == "b\n"
    assert ticket["worktree"]["repo_root"] == str(depots["demo"])
    assert _git(depots["outils"], "log", "-1", "--format=%s", f"agent/{ticket_id}") == "agent: b"
