# [desc] Tests de l'outil Environment : worktree demandé par l'agent, venv, merge et conflit. [/desc]
"""L'outil `Environment` vu du POINT D'ENTRÉE de l'agent.

On appelle l'outil comme le harness l'appelle (`_environment({"action": ...}, config)`) et on
vérifie les EFFETS RÉELS : le cwd du process a changé, une écriture en chemin relatif atterrit
dans le worktree, `git` répond dans le worktree, le signal IPC est déposé, le merge arrive dans
la branche de base, et un conflit est SIGNALÉ sans rien écraser.

Ces tests vivent dans `web_v2/tests/` pour bénéficier du conftest autouse qui redirige le store
de tickets, `WORKTREES_DIR` et la liste des projets vers `tmp_path` : l'outil appelle le VRAI
store et le VRAI provisionnement, donc sans cette isolation il écrirait en production.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from bouzecode.backend.tools import environment
from bouzecode.web_v2.runtime import env_signal
from bouzecode.web_v2.services.work import projects as work_projects
from bouzecode.web_v2.services.work import tickets as work_tickets

SLUG = "envtool"


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def _git_out(cwd, *args) -> str:
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    return (res.stdout or "").strip()


@pytest.fixture(autouse=True)
def _restore_cwd(monkeypatch):
    """L'outil fait un `os.chdir` RÉEL dans ce process et pose BOUZECODE_WORKTREE_ROOT : sans
    restauration, le test suivant démarrerait dans un worktree supprimé entre-temps, et l'outil
    Agent d'un autre test croirait déléguer depuis ce worktree (« fichiers NON commités »)."""
    monkeypatch.delenv("BOUZECODE_WORKTREE_ROOT", raising=False)
    before = os.getcwd()
    yield
    os.chdir(before)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "myrepo"
    path.mkdir()
    _git(path, "init")
    _git(path, "config", "user.name", "t")
    _git(path, "config", "user.email", "t@t")
    (path / "a.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-m", "init")
    return path


@pytest.fixture()
def agent(repo, tmp_path, monkeypatch):
    """Un agent porteur d'un ticket sur `repo`, avec son dossier IPC. Renvoie (ticket, config)."""
    # Le conftest isole déjà `projects.PROJECTS_PATH`, mais rien ne garantit que c'est LE module
    # que `provisioning._path_of` interroge : on patche celui-là explicitement avant d'écrire.
    projects_path = tmp_path / "work_projects.json"
    monkeypatch.setattr(work_projects, "PROJECTS_PATH", projects_path)
    projects_path.write_text(
        json.dumps([{"slug": SLUG, "name": "EnvTool", "path": str(repo)}]), encoding="utf-8")

    ticket = work_tickets.create_ticket(SLUG, "titre", "prompt")
    ipc = tmp_path / "agents" / "work-agent-env"
    ipc.mkdir(parents=True)
    #  L'agent qui appelle l'outil est le run EN COURS de son ticket (lot L2 : `running`).
    work_tickets.set_launching(SLUG, ticket)
    work_tickets.add_run(SLUG, ticket, "work-agent-env", "work", "m")

    monkeypatch.setenv("BOUZECODE_TICKET_SLUG", SLUG)
    monkeypatch.setenv("BOUZECODE_TICKET_ID", ticket["id"])
    # Ce process de test EST lui-même un agent en worktree : la variable est déjà posée et
    # ferait croire à l'outil qu'un worktree dédié existe. On repart d'une ardoise propre.
    monkeypatch.delenv("BOUZECODE_WORKTREE_ROOT", raising=False)
    os.chdir(repo)
    return ticket, {"_web_agent_dir": str(ipc)}


def _call(action: str, config: dict) -> str:
    return environment._environment({"action": action}, config)


# ── L'outil est bien exposé au modèle ──────────────────────────────────────

def test_environment_tool_is_registered_and_enabled():
    """Un outil enregistré mais absent de la whitelist est `disable_tool()` à l'import : il ne
    part JAMAIS au modèle. Ce test garde les deux moitiés du contrat."""
    from bouzecode.backend.core import tool_registry
    from bouzecode.backend.tools import registration  # noqa: F401 - peuple le registry

    assert "Environment" in tool_registry._registry
    assert "Environment" not in tool_registry._disabled


# ── worktree : création, déplacement, écriture, signal ─────────────────────

def test_worktree_moves_the_process_and_writes_land_there(agent, repo):
    ticket, config = agent

    out = _call("worktree", config)

    assert "Worktree dédié créé et adopté" in out
    fresh = work_tickets.get_ticket(SLUG, ticket["id"])
    worktree = Path(fresh["worktree"]["worktree"])
    assert worktree.is_dir()
    assert Path(os.getcwd()).resolve() == worktree.resolve(), "le cwd du process doit avoir bougé"

    # Un chemin RELATIF (ce que produisent Write/Edit et les commandes Bash) atterrit dedans.
    Path("nouveau.txt").write_text("depuis le worktree\n", encoding="utf-8")
    assert (worktree / "nouveau.txt").exists()
    assert not (repo / "nouveau.txt").exists()

    # git, lancé sans -C, voit le worktree et sa branche d'agent.
    top = Path(_git_out(os.getcwd(), "rev-parse", "--show-toplevel")).resolve()
    assert top == worktree.resolve()
    assert _git_out(os.getcwd(), "rev-parse", "--abbrev-ref", "HEAD") != "master"


def test_worktree_signals_the_new_cwd_to_the_server(agent, config_free=None):
    ticket, config = agent

    _call("worktree", config)

    signalled = env_signal.read(config["_web_agent_dir"])
    fresh = work_tickets.get_ticket(SLUG, ticket["id"])
    worktree = fresh["worktree"]["worktree"]
    assert Path(signalled["cwd"]).resolve() == Path(worktree).resolve()
    assert Path(signalled["worktree_root"]).resolve() == Path(worktree).resolve()
    assert Path(config["_web_agent_dir"], "env.json").exists()


def test_worktree_is_idempotent(agent):
    _, config = agent

    first = _call("worktree", config)
    second = _call("worktree", config)

    assert "créé et adopté" in first
    assert "Déjà en place" in second


# ── integrate : merge propre ───────────────────────────────────────────────

def test_integrate_merges_into_the_base_branch(agent, repo):
    ticket, config = agent
    _call("worktree", config)
    worktree = Path(os.getcwd())
    (worktree / "b.txt").write_text("travail de l'agent\n", encoding="utf-8")
    _git(worktree, "add", "b.txt")
    _git(worktree, "commit", "-m", "ajoute b")

    out = _call("integrate", config)

    assert "Merge propre" in out, out
    assert (repo / "b.txt").read_text(encoding="utf-8") == "travail de l'agent\n"
    fresh = work_tickets.get_ticket(SLUG, ticket["id"])
    #  Auto-intégration pendant son run : notée, conclue en transitions à la fin du run.
    assert fresh["integration"]["merged_at"] and fresh["integration"]["auto"]["issue"] == "integre"
    # Le cwd ne doit pas être un chemin détruit.
    assert Path(os.getcwd()).is_dir()
    assert Path(os.getcwd()).resolve() == repo.resolve()


# ── integrate : conflit signalé, rien d'écrasé ─────────────────────────────

def test_integrate_reports_conflict_without_overwriting(agent, repo):
    ticket, config = agent
    _call("worktree", config)
    worktree = Path(os.getcwd())
    (worktree / "a.txt").write_text("version agent\n", encoding="utf-8")
    _git(worktree, "add", "a.txt")
    _git(worktree, "commit", "-m", "agent edite a")
    # La base diverge sur le MÊME fichier → conflit garanti.
    (repo / "a.txt").write_text("version base\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "base edite a")

    out = _call("integrate", config)

    assert "CONFLIT au merge" in out, out
    assert "a.txt" in out
    # Rien d'écrasé : la base a gardé SA version, et le worktree survit pour la résolution.
    assert (repo / "a.txt").read_text(encoding="utf-8") == "version base\n"
    assert worktree.is_dir()
    assert Path(os.getcwd()).resolve() == worktree.resolve(), "l'agent revient chez lui"
    fresh = work_tickets.get_ticket(SLUG, ticket["id"])
    assert fresh["integration"]["conflict_files"] == ["a.txt"]
    assert fresh["integration"]["auto"]["issue"] == "conflit"


# ── refus explicites ──────────────────────────────────────────────────────

def test_outside_a_git_repo_worktree_is_refused(monkeypatch, tmp_path):
    """Le déclencheur de l'isolation est le DÉPÔT GIT, pas le ticket : sans dépôt, rien à isoler."""
    monkeypatch.delenv("BOUZECODE_TICKET_SLUG", raising=False)
    monkeypatch.delenv("BOUZECODE_TICKET_ID", raising=False)
    monkeypatch.delenv("BOUZECODE_WORKTREE_ROOT", raising=False)
    plain = tmp_path / "plain"
    plain.mkdir()
    os.chdir(plain)

    out = _call("worktree", {"_web_agent_dir": str(tmp_path)})

    assert "pas un dépôt git" in out


# ── hors ticket : le processus s'applique dès que c'est un dépôt git ───────

@pytest.fixture()
def solo(repo, tmp_path, monkeypatch):
    """Un agent SANS ticket (lancé à la main en TUI/CLI), dans un dépôt git."""
    monkeypatch.delenv("BOUZECODE_TICKET_SLUG", raising=False)
    monkeypatch.delenv("BOUZECODE_TICKET_ID", raising=False)
    # Ce process de test EST lui-même en worktree : sans ça, l'outil croirait déjà isolé.
    monkeypatch.delenv("BOUZECODE_WORKTREE_ROOT", raising=False)
    ipc = tmp_path / "agents" / "work-agent-solo"
    ipc.mkdir(parents=True)
    os.chdir(repo)
    return {"_web_agent_dir": str(ipc)}


def test_worktree_without_ticket_isolates_anyway_in_a_git_repo(solo, repo):
    out = _call("worktree", solo)

    cwd = Path(os.getcwd())
    assert not environment._same_path(str(cwd), str(repo)), out
    assert (cwd / "a.txt").exists(), "le worktree doit porter le contenu du dépôt"
    assert environment._branch_of(str(cwd)).startswith("agent/"), out
    assert environment._same_path(os.environ.get("BOUZECODE_WORKTREE_ROOT", ""), str(cwd))


def test_integrate_without_ticket_merges_into_the_base_branch(solo, repo):
    _call("worktree", solo)
    wt = Path(os.getcwd())
    (wt / "feature.txt").write_text("livre\n", encoding="utf-8")
    _git(wt, "add", "feature.txt")
    _git(wt, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "feat")

    out = _call("integrate", solo)

    assert "Merge propre" in out, out
    assert (repo / "feature.txt").exists(), "la livraison doit être dans la base"


def test_two_agents_without_ticket_never_share_a_branch(repo, tmp_path, monkeypatch):
    """Deux agents lancés sans ticket dans le MÊME dépôt doivent obtenir CHACUN son worktree,
    sur SA branche. Le défaut historique nommait tout agent sans dossier IPC « solo », donc
    tout le monde demandait `agent/solo` : le premier la créait, les suivants se voyaient
    refuser l'isolation et repartaient dans l'arbre partagé — l'inverse du but de l'outil."""
    monkeypatch.delenv("BOUZECODE_TICKET_SLUG", raising=False)
    monkeypatch.delenv("BOUZECODE_TICKET_ID", raising=False)
    monkeypatch.delenv("BOUZECODE_WORKTREE_ROOT", raising=False)
    os.chdir(repo)

    premier = _call("worktree", {})
    worktree_a, branche_a = os.getcwd(), environment._branch_of(os.getcwd())

    # Un SECOND process d'agent : il ne connaît pas le worktree du premier.
    monkeypatch.delenv("BOUZECODE_WORKTREE_ROOT", raising=False)
    os.chdir(repo)
    second = _call("worktree", {})
    worktree_b, branche_b = os.getcwd(), environment._branch_of(os.getcwd())

    assert "arbre partagé" not in second, second
    assert not environment._same_path(worktree_b, str(repo)), second
    assert branche_a.startswith("agent/"), premier
    assert branche_b.startswith("agent/"), second
    assert branche_a != branche_b, f"les deux agents partagent {branche_a}"
    assert not environment._same_path(worktree_a, worktree_b), (premier, second)
    assert (Path(worktree_b) / "a.txt").exists(), "le worktree doit porter le contenu du dépôt"


def test_venv_without_worktree_is_refused(agent):
    _, config = agent

    out = _call("venv", config)

    assert "Refusé : pas de venv dédié sans worktree dédié." in out


def test_integrate_without_worktree_says_nothing_to_do(agent):
    _, config = agent

    out = _call("integrate", config)

    assert "Rien à intégrer" in out


def test_unknown_action_is_named(agent):
    _, config = agent

    out = _call("teleporte-moi", config)

    assert "action inconnue" in out


# ── moitié SERVEUR du contrat : la reprise repart dans le worktree ─────────

def test_server_rehomes_the_agent_from_the_ipc_signal(agent, repo):
    """Le cas piège n'est pas « cwd détruit » mais « cwd ENCORE VALIDE mais PÉRIMÉ » : le
    serveur a mémorisé le dépôt partagé, l'agent s'est déplacé de lui-même. Sans lecture du
    signal, la reprise repartirait dans l'arbre partagé — exactement le bug qu'on corrige."""
    ticket, config = agent
    _call("worktree", config)
    worktree = Path(os.getcwd())

    from bouzecode.web_v2.runtime.runner import agent_fiche
    from bouzecode.web_v2.services.work import provisioning

    live = agent_fiche.Agent(
        agent_id="work-agent-env",
        prompt="p",
        model="m",
        cwd=str(repo),
        pid=0,
        started_at=0.0,
        ipc_dir=config["_web_agent_dir"],
        ticket_slug=SLUG,
        ticket_id=ticket["id"],
    )

    homed = provisioning.rehome_agent_cwd(live)

    assert Path(homed).resolve() == worktree.resolve()
    assert Path(live.cwd).resolve() == worktree.resolve()


# ── cleanup : c'est l'AGENT qui range derrière lui, comme un développeur ───

def _commit_some_work(worktree: Path, name: str = "b.txt") -> None:
    (worktree / name).write_text("travail de l'agent\n", encoding="utf-8")
    _git(worktree, "add", name)
    _git(worktree, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", f"ajoute {name}")


def test_integrate_keeps_the_worktree_and_orders_the_agent_to_clean(agent, repo):
    """Le merge ne DÉTRUIT plus l'atelier dans le dos de l'agent : il reste, et le message
    lui ORDONNE de le ranger — c'est lui qui nettoie, comme un dev supprime sa branche."""
    ticket, config = agent
    _call("worktree", config)
    worktree = Path(os.getcwd())
    _commit_some_work(worktree)

    out = _call("integrate", config)

    assert "Merge propre" in out, out
    assert (repo / "b.txt").exists(), "la livraison doit être dans la base"
    assert worktree.is_dir(), "le worktree doit SURVIVRE au merge : l'agent le nettoie lui-même"
    assert "Environment(action='cleanup')" in out, out
    fresh = work_tickets.get_ticket(SLUG, ticket["id"])
    assert fresh["integration"]["merged_at"] and not fresh["worktree"].get("retire_at")


def test_cleanup_removes_the_worktree_and_the_merged_branch(agent, repo):
    ticket, config = agent
    _call("worktree", config)
    worktree = Path(os.getcwd())
    branch = environment._branch_of(str(worktree))
    assert branch.startswith("agent/")
    _commit_some_work(worktree)
    _call("integrate", config)

    out = _call("cleanup", config)

    assert not worktree.exists(), out
    assert branch not in _git_out(repo, "branch", "--format=%(refname:short)").splitlines()
    fresh = work_tickets.get_ticket(SLUG, ticket["id"])
    assert fresh["worktree"]["retire_at"]
    assert Path(os.getcwd()).is_dir()


def test_cleanup_before_integration_is_refused(agent):
    """Ranger avant d'avoir livré détruirait le travail : refus explicite."""
    _, config = agent
    _call("worktree", config)
    worktree = Path(os.getcwd())

    out = _call("cleanup", config)

    assert "Refusé" in out, out
    assert worktree.is_dir(), "rien ne doit être supprimé sur un refus"


def test_cleanup_without_ticket_removes_the_worktree(solo, repo):
    """Hors ticket, `integrate` a déjà poppé BOUZECODE_WORKTREE_ROOT : `cleanup` doit tout de
    même savoir QUOI supprimer."""
    _call("worktree", solo)
    worktree = Path(os.getcwd())
    branch = environment._branch_of(str(worktree))
    _commit_some_work(worktree, "feature.txt")
    out_int = _call("integrate", solo)
    assert worktree.is_dir(), out_int

    out = _call("cleanup", solo)

    assert not worktree.exists(), out
    assert branch not in _git_out(repo, "branch", "--format=%(refname:short)").splitlines()


def test_cleanup_is_offered_to_the_model_and_taught_in_the_prompt():
    """Les deux moitiés du contrat : le verbe existe dans le schéma envoyé au modèle, ET le
    profil lui dit de l'appeler. Une consigne sans verbe ferait inventer un appel ; un verbe
    sans consigne ne serait jamais appelé."""
    import yaml

    assert "cleanup" in environment._ACTIONS
    assert "cleanup" in environment._SCHEMA["input_schema"]["properties"]["action"]["enum"]
    assert "cleanup" in environment._SCHEMA["description"]

    profile = Path(environment.__file__).parents[1] / "profiles" / "builtin" / "default.yaml"
    data = yaml.safe_load(profile.read_text(encoding="utf-8"))  # doit rester du YAML valide
    text = profile.read_text(encoding="utf-8")
    assert data, "default.yaml doit se charger"
    assert "action='cleanup'" in text, "le profil doit ORDONNER le nettoyage"


# ── worktree neuf : les dossiers ignorés par git (.venv, .cache) restés dans le dépôt ────

def test_worktree_signale_les_dossiers_ignores_restes_dans_le_depot(agent, repo):
    """Rapport docs/reduction_tokens §2.1 : 5 tours perdus à chercher `.venv`/`.cache` dans un
    worktree recréé. L'outil nomme les dossiers ignorés restés dans le dépôt principal."""
    ticket, config = agent
    (repo / ".gitignore").write_text(".venv/\n.cache/\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "ignore")
    (repo / ".cache" / "pdf").mkdir(parents=True)
    (repo / ".venv" / "bin").mkdir(parents=True)
    (repo / "pas_ignore").mkdir()

    out = _call("worktree", config)

    assert "Absents de ce worktree car ignorés par git" in out
    assert str(repo / ".cache") in out and str(repo / ".venv") in out
    assert "pas_ignore" not in out, "un dossier non ignoré n'est pas signalé"
    assert "Absents de ce worktree" in _call("status", config), "status le redit"


def test_la_fin_du_run_conclut_l_auto_integration(agent, repo):
    """L'agent s'est intégré pendant son run : quand son run se termine LIVRÉ, le ticket suit
    les transitions qu'il aurait suivies (delivered → integrating → closed{integre})."""
    from bouzecode.web_v2.services.work import constats
    ticket, config = agent
    _call("worktree", config)
    _commit_some_work(Path(os.getcwd()))
    _call("integrate", config)
    assert work_tickets.get_ticket(SLUG, ticket["id"])["state"] == "running"
    constats.fin_de_run(SLUG, ticket["id"], "work-agent-env", "final_answer")
    fresh = work_tickets.get_ticket(SLUG, ticket["id"])
    assert (fresh["state"], fresh["state_reason"]["code"]) == ("closed", "integre")
    assert "auto" not in fresh["integration"]
