# [desc] Fiche persistée d'un agent (dataclass `Agent`), lue/écrite dans `AGENTS_DIR`. [/desc]
"""Fiche d'un agent : la dataclass `Agent`, son JSON dans `AGENTS_DIR`, l'écriture atomique,
et le cache de la liste des fiches que chaque écriture invalide."""
from __future__ import annotations
from bouzecode.paths import data_dir as bouzecode_data_dir

import itertools
import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path


AGENTS_DIR = bouzecode_data_dir() / "web_agents"
AGENTS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Agent:
    agent_id: str
    prompt: str
    model: str
    cwd: str
    pid: int
    started_at: str
    finished_at: str = ""
    returncode: int | None = None
    stdout_path: str = ""
    session_path: str = ""
    ipc_dir: str = ""
    auto_retry_count: int = 0
    parent: str = ""  # manager agent_id, "dispatcher:manual", or "" (lancé hors manager)
    # Ticket identity + run kind, threaded to the subprocess as env so its
    # on_completion hook can notify /internal/runs/<agent_id>/ended. Persisted
    # here so continue_agent/_respawn re-inject them (env is rebuilt on respawn).
    ticket_slug: str = ""
    ticket_id: str = ""
    run_kind: str = "work"
    profile: str = ""  # resolved profile name (so a validator reuses the coder's)
    # Worktree racine d'un agent ISOLÉ (worktree dédié). Vide pour un agent non isolé
    # (CLI / non provisionné). Exposé en env BOUZECODE_WORKTREE_ROOT au (re)spawn pour
    # que le hook harness "hors worktree" sache quelle est la racine à comparer.
    worktree_root: str = ""
    # Venv du dépôt de BASE à utiliser, quand l'agent travaille dans un worktree pour lequel
    # AUCUN venv n'a été demandé (isolation `worktree`). Sans lui, l'agent n'a aucun
    # environnement Python et `uv` en fabrique un dans le worktree (~1 Go) que personne n'avait
    # demandé — cf. `runtime/venv_env.py`. Vide pour `shared` (le cwd EST le dépôt) et pour
    # `worktree+venv` (l'agent a le sien). Persisté : rejoué à chaque respawn.
    base_venv: str = ""
    # Motif du DERNIER refus de terminaison par l'OS ("" si la dernière tentative a abouti
    # ou n'a pas eu lieu). Un `AccessDenied` sur un pid est un cas courant sous Windows :
    # il ne doit ni tuer le serveur, ni disparaître en silence. Servi tel quel par l'API.
    termination_error: str = ""
    # IDENTITÉ du process : son instant de création (epoch), lu à chaque spawn. Un pid est
    # RECYCLÉ par l'OS dès que son process meurt ; sans cette référence, un pid réattribué à un
    # programme tiers faisait passer l'agent pour vivant à jamais. 0.0 = fiche antérieure (on
    # ne juge alors que l'existence du pid, comme avant).
    pid_create_time: float = 0.0
    # Agent RELANCÉ depuis la session d'un autre (`resume_agent`) : l'agent repris et le titre
    # lisible de ce qu'il faisait. Sans eux, la liste des agents l'appelait par son prompt de
    # reprise (« Reprends la tâche interrompue là où elle s'est arrêtée. »).
    reprise_de: str = ""
    # Sens inverse : l'agent qui a REPRIS celui-ci. Sans ce lien, un observateur qui suivait
    # l'ancienne fiche y lisait à jamais le pid mort de l'ancien process et déclarait morte une
    # reprise pourtant vivante (sous un NOUVEL identifiant, cf. `resume_agent`).
    reprise_par: str = ""
    titre: str = ""
    # Raison LISIBLE d'une fin CONSTATÉE par le serveur (process disparu, pid réutilisé,
    # zombie ramassé) — par opposition à une fin annoncée par l'agent. Vide sinon.
    fin_constatee: str = ""
    # Jeton PROPRE AU RUN (spec ticketing §6.5) : généré au spawn, transmis à l'agent par son
    # env (`BOUZECODE_RUN_TOKEN`), exigé par `POST /internal/runs/<agent_id>/ended`. Vide pour
    # une fiche d'avant L3 : son hook n'annonce rien, le watchdog constate sa fin.
    run_token: str = ""


def _agent_json_path(agent_id: str) -> Path:
    return AGENTS_DIR / f"{agent_id}.json"


_temp_counter = itertools.count()


def _temp_suffix() -> str:
    return f"{os.getpid()}.{threading.get_ident()}.{next(_temp_counter)}"


def _save(agent: Agent) -> None:
    # Atomic write: dump to a temp then replace, so a concurrent reader
    # (list_agents refreshes status on every request) never sees a half-written
    # or shorter-overwrites-longer file (which left a stray trailing `}`).
    # The temp name is unique PER CALL (pid + thread + counter), not per pid: two threads of
    # the server saving the same agent shared `<id>.<pid>.tmp`, and the second `replace`
    # found the file already moved (FileNotFoundError -> transient 500).
    path = _agent_json_path(agent.agent_id)
    tmp_path = path.with_name(f"{path.name}.{_temp_suffix()}.tmp")
    try:
        tmp_path.write_text(json.dumps(asdict(agent), indent=2), encoding="utf-8")
        _replace_with_retry(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)
    # Invalidate the list_agents cache: a saved agent changed status, so the next
    # list_agents() must re-read from disk instead of serving a stale snapshot
    # (otherwise the kanban/ticket UI flickers with an out-of-date state).
    invalidate_agents_cache()


def _replace_with_retry(tmp_path: Path, path: Path, attempts: int = 12) -> None:
    """Windows : os.replace lève WinError 32 si un lecteur concurrent (list_agents rafraîchit
    le statut à CHAQUE requête, + le tick wake) tient le .json cible ouvert. Le verrou est
    TRANSITOIRE ; sans retry ça remontait en 500 (/api/projects/logical) et fragilisait le
    serveur. On retente brièvement (~1 s cumulé) avant d'abandonner."""
    for i in range(attempts):
        try:
            tmp_path.replace(path)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.02 * (i + 1))


def load_agent(agent_id: str) -> Agent | None:
    path = _agent_json_path(agent_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logging.getLogger(__name__).warning(
            "Skipping corrupt agent file %s: %s", path, exc
        )
        return None
    return _agent_from_dict(data)


_REQUIRED_KEYS = {"agent_id", "prompt", "model", "cwd", "pid", "started_at"}


def _agent_from_dict(data: dict) -> Agent | None:
    """Build Agent from dict, ignoring unknown keys. Returns None if required keys missing."""
    # Le dossier des agents héberge aussi d'autres JSON (ex. `<id>.queue.json`, une LISTE de
    # messages en file) : tout ce qui n'est pas une fiche d'agent est ignoré, jamais une erreur.
    if not isinstance(data, dict) or not _REQUIRED_KEYS.issubset(data):
        return None
    valid = {f.name for f in Agent.__dataclass_fields__.values()}
    return Agent(**{k: v for k, v in data.items() if k in valid})


_list_agents_cache: dict = {}
_list_agents_lock = threading.Lock()


def invalidate_agents_cache() -> None:
    """Oublie la liste mémorisée : le prochain `list_agents()` relit le disque.

    Public par nécessité : qui vient d'écrire des agents sur disque (sauvegarde d'agent,
    test qui pose ses propres fichiers) doit pouvoir invalider ce cache SANS toucher aux
    internes du module."""
    _list_agents_cache.pop("expires", None)
