"""Le Bureau ne se rafraîchissait plus : `GET /api/inbox` dépassait les 30 s du front
(`bureau/main.js charger()`), qui affichait « Rafraîchissement du Bureau impossible ».

Mesuré à froid sur les données réelles : /api/inbox = 14,1 s, dont 10,8 s pour le seul
bloc `inbox._conversations_arretees`, lui-même dominé par `fleet._prewarm_git` (5,6 s de
subprocess git) — alors que cette carte ne lit AUCUN champ git (agent_id, title, key,
saved_at, project_slug). L'inbox demande donc désormais un arbre SANS git.

Assertions observables uniquement (aucun timing, interdit ici) : le contrat est « le
chemin inbox ne déclenche aucune résolution git », prouvé par les caches de `repos` qui
restent vides — exactement l'inverse de `test_fleet_warm.test_warm_populates_repos_caches`.
"""
import json
import os
import subprocess
from datetime import datetime, timezone

from bouzecode.web_v2.services.work import fleet, inbox, tickets, projects, repos
from bouzecode.web_v2.services.sessions import store, purge
from bouzecode.web_v2.runtime.runner import agent_etat, agent_fiche, agent_registre, agent_vivacite


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
        # pid=0 → runner.is_warm renvoie False ; le node se construit normalement.
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
    """Isole l'arbre fleet : agents contrôlés, caches git froids, mémo d'arbre vidé."""
    monkeypatch.setattr(agent_registre, "list_agents", lambda: agents)
    monkeypatch.setattr(agent_etat, "refresh_agent_status", lambda a: a)
    monkeypatch.setattr(agent_etat, "get_ipc_state", lambda a: {})
    monkeypatch.setattr(agent_vivacite, "is_running", lambda a: True)
    monkeypatch.setattr(store, "list_agent_sessions", lambda: [])
    monkeypatch.setattr(purge, "load_deleted", lambda: set())
    monkeypatch.setattr(projects, "list_projects", lambda: [])
    monkeypatch.setattr(projects, "project_for_cwd", lambda cwd, plist: None)
    monkeypatch.setattr(tickets, "launching_tickets", lambda: [])
    # Caches froids : toute résolution git laisserait une trace ici.
    repos._key_cache.clear()
    repos._branch_cache.clear()
    fleet.clear_tree_cache()


def _git_touche():
    """Vrai si une information git a été résolue (au moins un cwd mis en cache)."""
    return bool(repos._key_cache) or bool(repos._branch_cache)


def test_arbre_sans_git_ne_resout_aucune_info_git(monkeypatch, tmp_path):
    """`avec_git=False` : les nodes sortent sans repo/branch et AUCUN subprocess git
    n'est payé (les caches de `repos` restent vides)."""
    repo = str(tmp_path / "repo")
    _git_repo(repo, "feature-a")
    _wire(monkeypatch, [_FakeAgent("ag-a", cwd=repo)])

    tree = fleet._agent_tree_uncached(avec_git=False)

    node = {n["agent_id"]: n for n in tree["nodes"]}["ag-a"]
    assert node["repo"] == ""
    assert node["branch"] == ""
    assert not _git_touche()


def test_arbre_par_defaut_garde_repo_et_branche(monkeypatch, tmp_path):
    """Non-régression de la sidebar Conversations : sans rien demander, l'arbre porte
    toujours la branche et le dépôt réels."""
    repo = str(tmp_path / "repo")
    _git_repo(repo, "feature-b")
    _wire(monkeypatch, [_FakeAgent("ag-b", cwd=repo)])

    tree = fleet._agent_tree_uncached()

    node = {n["agent_id"]: n for n in tree["nodes"]}["ag-b"]
    assert node["branch"] == "feature-b"
    assert node["repo"]


def test_inbox_ne_paie_pas_le_git_de_la_flotte(monkeypatch, tmp_path):
    """Le bloc le plus lourd de /api/inbox (`_conversations_arretees`) construit ses
    cartes sans déclencher la moindre résolution git."""
    repo = str(tmp_path / "repo")
    _git_repo(repo, "feature-c")
    _wire(monkeypatch, [_FakeAgent("ag-c", cwd=repo)])

    inbox._conversations_arretees(set())

    assert not _git_touche()


def _agent_vivant_sur_disque(agents_dir, agent_id, cwd):
    """Pose un agent VIVANT là où le runtime les lit (`runner.AGENTS_DIR`), au lieu de
    remplacer `runner.list_agents` : le test voit le même disque que le serveur."""
    (agents_dir / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id,
        "prompt": "fais le truc",
        "model": "sonnet",
        "cwd": cwd,
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "returncode": None,
        "ipc_dir": "",
    }), encoding="utf-8")
    (agents_dir / f"{agent_id}.session.json").write_text(
        json.dumps({"close_reason": "", "final_answer": ""}), encoding="utf-8")


def _espion_git(monkeypatch):
    """Compte les résolutions git via l'API PUBLIQUE de `repos` (pas ses caches privés).
    Rend la liste des noms appelés, qui se remplit au fil des requêtes."""
    appels = []
    for nom in ("repo_key", "branch_of"):
        origine = getattr(repos, nom)

        def espion(*args, _nom=nom, _origine=origine, **kwargs):
            appels.append(_nom)
            return _origine(*args, **kwargs)

        monkeypatch.setattr(repos, nom, espion)
    return appels


def test_nav_counts_ne_resout_aucune_info_git(monkeypatch, tmp_path):
    """`GET /api/nav/counts` (pastilles de la nav, appelé par CHAQUE page) n'affiche que
    trois entiers : il ne doit résoudre AUCUNE information git. Mesuré sur les données
    réelles avant correctif : 28,9 s à froid dont 15,1 s en 284 subprocess git.

    Test au niveau HTTP, sur des agents posés sur disque : aucun privé de `fleet`/`repos`,
    donc il survit à un remaniement de la construction de l'arbre. `/api/agents/tree`,
    appelé ensuite, sert de contrôle : il résout du git sur LES MÊMES données, ce qui
    prouve que l'assertion ci-dessus n'est pas vraie par accident."""
    from bouzecode.web_v2.app import create_app

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    repo = str(tmp_path / "repo")
    _git_repo(repo, "feature-nav")
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", agents_dir)
    _agent_vivant_sur_disque(agents_dir, "ag-nav", repo)
    agent_fiche.invalidate_agents_cache()
    fleet.clear_tree_cache()

    appels = _espion_git(monkeypatch)
    client = create_app().test_client()

    counts = client.get("/api/nav/counts").get_json()

    assert appels == [], f"les pastilles ont résolu du git : {appels}"

    tree = client.get("/api/agents/tree").get_json()

    assert appels, "contrôle : /api/agents/tree devait, lui, résoudre du git"
    attendu = sum(1 for n in tree.get("nodes") or []
                  if n.get("etat") in inbox.ETATS_AU_TRAVAIL)
    assert counts["en_cours"] == attendu


def test_cartes_identiques_avec_et_sans_git(monkeypatch, tmp_path):
    """Le fonctionnel ne change pas : les mêmes agents donnent les mêmes cartes
    `agent_arrete` (id, titre, key, projet) que l'arbre porte le git ou non."""
    repo = str(tmp_path / "repo")
    _git_repo(repo, "feature-d")
    agents = [_FakeAgent("ag-d", cwd=repo), _FakeAgent("ag-e", cwd=repo)]

    _wire(monkeypatch, agents)
    # On force l'arbre AVEC git, puis l'arbre SANS git, sans jamais passer par le vrai
    # `agent_tree` (cache + store tickets : hors sujet ici, et interdit par l'isolation).
    monkeypatch.setattr(
        fleet, "agent_tree", lambda *a, **k: fleet._agent_tree_uncached(avec_git=True))
    reference = inbox._conversations_arretees(set())

    monkeypatch.setattr(
        fleet, "agent_tree", lambda *a, **k: fleet._agent_tree_uncached(avec_git=False))
    obtenu = inbox._conversations_arretees(set())

    cle = lambda cartes: sorted(  # noqa: E731
        (c["id"], c["titre"], c["key"], c["projet_slug"]) for c in cartes)
    assert cle(obtenu) == cle(reference)
