"""fleet._agent_tree_uncached() pré-warm les infos git (repo_key/branch_of) des
cwd uniques en parallèle AVANT de construire les nodes, pour éviter le N+1 de
subprocess git séquentiels qui rendait la sidebar Conversations bloquée 2 min+ à
froid (~1000 agents × subprocess git).

Ce test vérifie la CORRECTNESS : le warm parallèle ne doit PAS changer le résultat
fonctionnel. On monte de vrais dépôts git temporaires (avec des branches nommées
distinctes), on enregistre des agents fictifs pointant dessus, et on asserte que
chaque node porte la branche et le repo réels résolus par repos.branch_of/repo_key.
Aucun mock de repos, aucune assertion de timing (implementation-detail interdit)."""
import os
import subprocess

from bouzecode.web_v2.services.work import fleet, tickets, projects, repos
from bouzecode.web_v2.services.sessions import store, purge
from bouzecode.web_v2.runtime import runner


class _FakeAgent:
    """Agent web tel que renvoyé par runner.list_agents (champs lus par _node)."""

    def __init__(self, agent_id: str, cwd: str):
        self.agent_id = agent_id
        self.ticket_id = ""
        self.session_path = ""
        self.returncode = None
        self.model = ""
        self.prompt = "prompt agent"
        self.parent = ""
        self.cwd = cwd
        self.started_at = "2026-07-15T11:00:00"
        self.profile = ""
        self.run_kind = "work"
        # Champs lus par runner.is_warm (fleet._node badge 'chaud') : sans eux
        # is_warm lève AttributeError. pid=0 → is_warm renvoie False (agent pas chaud),
        # le node se construit normalement — le contrat branch/repo reste prouvé.
        self.pid = 0
        self.ipc_dir = ""
        self.finished_at = ""


def _git_repo(path, branch):
    """Crée un vrai dépôt git à `path` avec un commit et la branche courante `branch`."""
    os.makedirs(path, exist_ok=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    }

    def run(*args):
        subprocess.run(["git", "-C", path, *args], check=True,
                       capture_output=True, env=env)

    subprocess.run(["git", "init", path], check=True, capture_output=True, env=env)
    run("checkout", "-b", branch)
    with open(os.path.join(path, "f.txt"), "w") as fh:
        fh.write("x")
    run("add", ".")
    run("commit", "-m", "init")


def _wire(monkeypatch, agents):
    monkeypatch.setattr(runner, "list_agents", lambda: agents)
    monkeypatch.setattr(runner, "refresh_agent_status", lambda a: a)
    monkeypatch.setattr(runner, "get_ipc_state", lambda a: {})
    monkeypatch.setattr(runner, "is_running", lambda a: True)
    monkeypatch.setattr(store, "list_agent_sessions", lambda: [])
    monkeypatch.setattr(purge, "load_deleted", lambda: set())
    monkeypatch.setattr(projects, "list_projects", lambda: [])
    monkeypatch.setattr(projects, "project_for_cwd", lambda cwd, plist: None)
    monkeypatch.setattr(tickets, "launching_tickets", lambda: [])
    # Caches froids : on veut que le warm parallèle résolve vraiment via git.
    repos._key_cache.clear()
    repos._branch_cache.clear()


def test_warm_preserves_branch_and_repo(monkeypatch, tmp_path):
    """Après le pré-warm parallèle, chaque node porte la branche + le repo réels
    de son worktree git (le warm ne dénature pas le résultat)."""
    repo_a = str(tmp_path / "repoA")
    repo_b = str(tmp_path / "repoB")
    _git_repo(repo_a, "feature-a")
    _git_repo(repo_b, "feature-b")
    agents = [
        _FakeAgent("ag-a", cwd=repo_a),
        _FakeAgent("ag-b", cwd=repo_b),
    ]
    _wire(monkeypatch, agents)

    tree = fleet._agent_tree_uncached()
    by_id = {n["agent_id"]: n for n in tree["nodes"]}

    assert by_id["ag-a"]["branch"] == "feature-a"
    assert by_id["ag-b"]["branch"] == "feature-b"
    # repo_name dérive du dépôt réel → non vide pour un vrai worktree git.
    assert by_id["ag-a"]["repo"]
    assert by_id["ag-b"]["repo"]


def test_warm_populates_repos_caches(monkeypatch, tmp_path):
    """Le warm remplit repos._key_cache/_branch_cache pour les cwd des agents :
    les appels _node suivants lisent en cache (0 subprocess séquentiel)."""
    repo = str(tmp_path / "repo")
    _git_repo(repo, "main")
    _wire(monkeypatch, [_FakeAgent("ag", cwd=repo)])

    fleet._agent_tree_uncached()

    assert repo in repos._key_cache
    assert repo in repos._branch_cache
    assert repos._branch_cache[repo][1] == "main"
