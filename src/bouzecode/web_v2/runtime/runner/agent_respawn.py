# [desc] Relance d'un agent sur SA session (`_respawn`) : verrou anti double-spawn, cwd sûr, signal d'environnement. [/desc]
"""Relance d'un agent sur sa propre session : verrou par agent et garde anti-jumeau, cwd de
repli si le worktree a disparu, adoption du déplacement signalé par l'agent."""
from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path

from .. import env_signal
from . import agent_fiche
from . import agent_commande
from . import agent_vivacite
from . import agent_processus
from .agent_fiche import Agent


# Verrous d'idempotence de spawn, un par agent_id. Sous threaded=True, deux threads peuvent
# vouloir respawn le MÊME agent (réveil + action manuelle, retry + resume…) et lancer deux
# process sur le MÊME --session-file → double-spawn (2× tokens, jumeau non-tracké). Le verrou
# sérialise, et le contrôle « un process tourne-t-il déjà pour cette session » ferme la course.
_spawn_locks: dict = {}
_spawn_locks_guard = threading.Lock()


def _agent_spawn_lock(agent_id: str):
    with _spawn_locks_guard:
        return _spawn_locks.setdefault(agent_id, threading.Lock())


def _is_dead_worktree(cwd: str) -> bool:
    """A worktree path (under ~/.bouzecode/worktrees) that no longer holds a `.git` link is
    DEAD: after a merge+reap the folder can survive on disk — readme_sync even repaints a
    solitary AGENTS.md — while the code AND the git link vanished. Popen-ing an agent there
    revives it in an empty dir ('worktree vide' → blocked awaiting_input). os.path.isdir alone
    can't tell this apart from a live checkout, so we key on the worktrees marker + missing .git.
    Only worktree paths are judged: a non-git project runs agents directly in its own dir."""
    parts = Path(cwd).parts
    under_worktrees = (".bouzecode" in parts or ".bouzecode" in parts) and "worktrees" in parts
    return under_worktrees and not os.path.exists(os.path.join(cwd, ".git"))


def _safe_cwd(cwd: str) -> str | None:
    """Last-resort floor for a respawn whose worktree was cleaned away (ticket merged then
    worktree removed): passing a vanished — or emptied — dir to subprocess.Popen either raises
    NotADirectoryError (bogus HTTP 500 the UI mislabels 'interrupt the agent first') or, worse,
    silently revives the agent in a code-less worktree. Fall back to the server's cwd (the live
    checkout) when the dir is gone OR is a dead worktree. The /continue route re-homes to a fresh
    worktree BEFORE respawn (dispatch.rehome_agent_cwd); this backstops every path that bypasses
    it — including ticketless manager sub-agents that rehome cannot re-provision."""
    if not (cwd and os.path.isdir(cwd)):
        return None
    if _is_dead_worktree(cwd):
        return None
    return cwd


def _meme_dossier(a: str, b: str) -> bool:
    return bool(a and b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _adopter_le_signal_d_environnement(agent: "Agent") -> None:
    """L'agent s'est déplacé LUI-MÊME en vol (outil Environment : worktree, intégration) et l'a
    signalé dans `env.json`. Un respawn qui l'ignorait relançait le manager réveillé dans le
    dépôt principal : son commit n'y voyait rien (constaté en recette). Dernier filet commun à
    TOUS les chemins de reprise (réveil, message, résolution de conflit, file de messages)."""
    signal = env_signal.read(agent.ipc_dir)
    cwd = signal.get("cwd", "")
    if not (cwd and os.path.isdir(cwd)):
        return
    agent.cwd = cwd
    racine = signal.get("worktree_root", "")
    dans_son_worktree = _meme_dossier(racine, cwd)
    agent.worktree_root = racine if dans_son_worktree else ""
    #  Un venv de worktree ne vaut que DANS ce worktree (après intégration, l'agent est revenu
    #  dans le dépôt principal : garder ce venv le ferait tourner sur un dossier disparu).
    if dans_son_worktree and signal.get("base_venv"):
        agent.base_venv = signal["base_venv"]


def _respawn(agent: Agent, extra_args: list[str], banner: str, model: str = "") -> "Agent | None":
    """Shared respawn logic: clean IPC, launch subprocess, update agent state.

    Ré-utilise le MÊME --session-file (contrairement à resume_agent qui en crée un neuf) →
    seul point où deux threads peuvent lancer un jumeau sur une même session. Sérialisé par
    _agent_spawn_lock + garde d'idempotence (double-spawn évité à la racine)."""
    use_model = model or agent.model
    with _agent_spawn_lock(agent.agent_id):
        # Un process tourne déjà pour cette session (autre thread ayant respawné pendant l'attente
        # du verrou, ou précédent non encore mort) → NE PAS lancer de jumeau (2× tokens).
        if agent_processus._session_process_running(agent.session_path):
            logging.getLogger(__name__).warning(
                "respawn ignoré (double-spawn évité) : process déjà vivant pour %s",
                agent.session_path)
            return None  # respawn NON effectué → l'appelant (continue_coder) ne doit
            # PAS enregistrer de run 'work' fantôme qui brûlerait le plafond de passes.

        # Le nettoyage IPC ci-dessous efface `env.json` : adopter AVANT ce que l'agent y a
        # signalé (worktree où il s'est déplacé en vol), sinon il repart dans l'ancien cwd.
        _adopter_le_signal_d_environnement(agent)
        if agent.ipc_dir:
            ipc_path = Path(agent.ipc_dir)
            for f in ipc_path.iterdir():
                try:
                    f.unlink()
                except OSError:
                    pass

        cmd = agent_commande._agent_cmd()
        if use_model:
            cmd += ["-m", use_model]
        cmd += agent_commande._profile_launch_args(agent.profile)
        cmd += [
            "--session-file", agent.session_path,
            "--resume-from", agent.session_path,
            "--web-agent-dir", agent.ipc_dir,
            *extra_args,
        ]

        stdout_file = Path(agent.stdout_path).open("ab")
        stdout_file.write(banner.encode("utf-8"))
        stdout_file.flush()

        process = subprocess.Popen(
            cmd,
            cwd=_safe_cwd(agent.cwd),
            stdout=stdout_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        creationflags=agent_commande.DRAPEAUX_DE_SPAWN,
            env=agent_commande._spawn_env(**agent_commande._ticket_env(agent)),
        )

        agent.pid = process.pid
        agent.pid_create_time = agent_vivacite._instant_de_creation(process.pid)
        agent.model = use_model
        agent.finished_at = ""
        agent.returncode = None
        agent.fin_constatee = ""
        agent_fiche._save(agent)
        from ...services.work import fleet_cache  # local : `fleet` importe ce module
        fleet_cache.expire_all()  # l'arbre montrait encore l'agent « terminé » après sa relance
        return agent
