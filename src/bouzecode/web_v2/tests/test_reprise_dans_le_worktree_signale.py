# [desc] Une reprise à froid (réveil, message) relance l'agent là où il s'est déplacé en vol (env.json), pas dans son cwd de lancement. [/desc]
"""Recette du 2026-09-24 : un manager se met en worktree (outil Environment, `os.chdir` dans SON
process + `env.json` dans son dossier IPC), délègue, rend la main. Réveillé par le serveur, il
était respawné avec `agent.cwd` = le dépôt principal (et `_respawn` effaçait `env.json` au
passage) : son `git commit` y voyait « nothing to commit » et son travail restait orphelin."""
import subprocess
import sys

from bouzecode.web_v2.runtime.runner import agent_fiche, agent_reprise, agent_respawn
from bouzecode.web_v2.runtime import env_signal


_POPEN = subprocess.Popen


class _Capture:
    """Popen de substitution : un vrai process (qui se termine aussitôt) dont on garde cwd/env."""

    def __init__(self):
        self.cwd = None
        self.env = None

    def __call__(self, cmd, cwd=None, env=None, **kwargs):
        self.cwd, self.env = cwd, env
        return _POPEN([sys.executable, "-c", "pass"], **kwargs)


def _agent(tmp_path, depot, worktree):
    ipc = tmp_path / "a1.ipc"
    ipc.mkdir()
    agent = agent_fiche.Agent(
        agent_id="a1", prompt="Coordonner", model="", cwd=str(depot), pid=0,
        started_at="2026-09-24T10:00:00Z", finished_at="2026-09-24T10:05:00Z", returncode=0,
        stdout_path=str(tmp_path / "a1.out.log"), session_path=str(tmp_path / "a1.session.json"),
        ipc_dir=str(ipc),
    )
    (tmp_path / "a1.session.json").write_text(
        '{"messages": [{"role": "user", "content": "Coordonner"}]}', encoding="utf-8")
    return agent


def _dossiers(tmp_path):
    depot = tmp_path / "depot"
    depot.mkdir()
    worktree = tmp_path / ".bouzecode" / "worktrees" / "depot" / "w1"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: ...", encoding="utf-8")
    return depot, worktree


def test_le_manager_reveille_repart_dans_son_worktree(tmp_path, monkeypatch):
    depot, worktree = _dossiers(tmp_path)
    agent = _agent(tmp_path, depot, worktree)
    env_signal.write(agent.ipc_dir, cwd=str(worktree), worktree_root=str(worktree))
    capture = _Capture()
    monkeypatch.setattr(agent_respawn.subprocess, "Popen", capture)

    assert agent_reprise.continue_agent(agent, "Tes enfants ont fini.") is not None

    assert capture.cwd == str(worktree)
    assert capture.env["BOUZECODE_WORKTREE_ROOT"] == str(worktree)
    assert agent_fiche.load_agent("a1").cwd == str(worktree)   # persisté : la reprise suivante aussi


def test_apres_integration_il_repart_dans_le_depot_sans_racine_de_worktree(tmp_path, monkeypatch):
    depot, worktree = _dossiers(tmp_path)
    agent = _agent(tmp_path, depot, worktree)
    agent.cwd = str(worktree)
    agent.worktree_root = str(worktree)
    #  `integrate` a ramené l'agent dans le dépôt ; le fichier garde l'ancienne racine (les
    #  champs vides ne s'écrivent pas) : elle ne doit pas être rejouée.
    env_signal.write(agent.ipc_dir, cwd=str(worktree), worktree_root=str(worktree))
    env_signal.write(agent.ipc_dir, cwd=str(depot))
    capture = _Capture()
    monkeypatch.setattr(agent_respawn.subprocess, "Popen", capture)

    agent_reprise.continue_agent(agent, "suite")

    assert capture.cwd == str(depot)
    #  (l'env hérite de celui du process de test : on vérifie que l'ANCIENNE racine n'est pas
    #  rejouée, pas l'absence d'une variable qu'un autre test aurait pu poser)
    assert capture.env.get("BOUZECODE_WORKTREE_ROOT") != str(worktree)
    assert agent_fiche.load_agent("a1").worktree_root == ""
