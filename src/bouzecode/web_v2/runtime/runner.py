# [desc] Spawns, persists, and tracks bouzecode CLI subprocess agents with status refresh. [/desc]
"""Spawn and track bouzecode subprocess agents."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import psutil

from . import deferred as web_deferred
from . import ipc
from . import pending as web_pending
from . import venv_env
from .. import close_reasons


AGENTS_DIR = Path.home() / ".bouzecode" / "web_agents"
AGENTS_DIR.mkdir(parents=True, exist_ok=True)


_MAX_AUTO_RETRIES = 3


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
    # on_completion hook can notify /api/tickets/<slug>/<id>/completed. Persisted
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


# Sentinelle de `parent` pour un agent lancé À LA MAIN depuis l'UI. Ce n'est PAS une parenté :
# aucun manager ne l'a créé, et il a un utilisateur qui reviendra lui écrire. Défini ici, au
# plus bas niveau, parce que c'est ici qu'on décide ce qui part dans l'env du process spawné
# (`_ticket_env`) ; `services.work.dispatch` le ré-exporte pour ses propres lectures, afin que
# la chaîne « lancé à la main » n'ait qu'UNE définition.
MANUAL_PARENT = "dispatcher:manual"


def _agent_json_path(agent_id: str) -> Path:
    return AGENTS_DIR / f"{agent_id}.json"


def _save(agent: Agent) -> None:
    # Atomic write: dump to a per-pid temp then replace, so a concurrent reader
    # (list_agents refreshes status on every request) never sees a half-written
    # or shorter-overwrites-longer file (which left a stray trailing `}`).
    path = _agent_json_path(agent.agent_id)
    tmp_path = path.with_suffix(f".{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(asdict(agent), indent=2), encoding="utf-8")
    _replace_with_retry(tmp_path, path)
    # Invalidate the list_agents cache: a saved agent changed status, so the next
    # list_agents() must re-read from disk instead of serving a stale snapshot
    # (otherwise the kanban/ticket UI flickers with an out-of-date state).
    _list_agents_cache.pop("expires", None)


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


def _bouzecode_launch_cmd() -> list[str]:
    """Launch bouzecode via `python -m bouzecode` — avoids Windows .exe shim file locks.
    -P (PYTHONSAFEPATH) : le cwd de l'agent ne doit pas pouvoir shadower le package
    bouzecode (ex. projet avec un bouzecode.py racine, comme bouzecode_oss)."""
    return [sys.executable, "-P", "-m", "bouzecode"]


def _spawn_env(**extra: str) -> dict:
    """Env des agents spawnés : le package bouzecode du serveur doit gagner quel que
    soit le cwd (avec -P, le cwd sort de sys.path ; PYTHONPATH garantit la résolution).

    ⚠️ Les indices `parents[N]` sont comptés depuis `src/bouzecode/web_v2/runtime/runner.py`.
    Ils valaient un cran de moins tant que ce fichier vivait dans `web_v2/` ; le déplacement
    vers `runtime/` ne les a pas décalés, et PYTHONPATH pointait donc DANS le package
    (`src/bouzecode`) au lieu de `src` — `import bouzecode` ne résolvait plus depuis la racine
    du serveur, ce qui est exactement la garantie anti-shadowing que cette fonction existe
    pour tenir."""
    pkg_root = str(Path(__file__).resolve().parents[3])
    previous = os.environ.get("PYTHONPATH", "")
    # readme_sync lives at the server repo root (not under src/, not shipped in the
    # wheel). With -P the cwd leaves sys.path, so the package is unreachable unless
    # we add the repo root here. Added AFTER pkg_root so the bouzecode package always
    # wins first (no shadowing), and only when readme_sync actually exists there.
    extra_roots = []
    repo_root = Path(__file__).resolve().parents[4]
    if (repo_root / "readme_sync" / "__init__.py").exists():
        extra_roots.append(str(repo_root))
    pythonpath = os.pathsep.join([pkg_root, *extra_roots] + ([previous] if previous else []))
    return {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": pythonpath,
        **extra,
    }


def _ticket_env(agent: "Agent") -> dict:
    """Env carrying the agent's ticket identity + run kind, so its on_completion
    hook can POST /api/tickets/<slug>/<id>/completed. Rebuilt on every (re)spawn
    from the persisted Agent fields — survives continue_agent."""
    env: dict[str, str] = {"BOUZECODE_RUN_KIND": agent.run_kind or "work"}
    # Parenté : un SOUS-AGENT ne doit pas rester chaud. Le quart d'heure de résidence existe
    # pour laisser à l'UTILISATEUR le temps de revenir sur sa conversation ; un sous-agent
    # n'a pas d'utilisateur. Le process ne connaissait pas sa parenté (seul le serveur la
    # connaît), donc `_web_keep_warm` gardait TOUT le monde résident, y compris les douze
    # sous-agents d'un manager.
    #
    # ⚠️ `MANUAL_PARENT` N'EST PAS UNE PARENTÉ : c'est le sentinelle « lancé à la main depuis
    # l'UI ». Le poser ici éteignait le warm-pool pour les SEULES conversations qu'il existe
    # pour servir. Constat du 2026-08-03 sur le parc réel : 54 conversations utilisateur,
    # 54 process morts, 0 warm — donc respawn à froid à CHAQUE message ET à chaque follow-up,
    # là où la TUI garde son process entre les tours. C'est l'écart que l'utilisateur ressent.
    if agent.parent and agent.parent != MANUAL_PARENT:
        env["BOUZECODE_PARENT"] = agent.parent
    if agent.ticket_slug:
        env["BOUZECODE_TICKET_SLUG"] = agent.ticket_slug
    if agent.ticket_id:
        env["BOUZECODE_TICKET_ID"] = agent.ticket_id
    if agent.worktree_root:
        env["BOUZECODE_WORKTREE_ROOT"] = agent.worktree_root
    # Venv du dépôt de base : c'est ce qui empêche un worktree SANS venv demandé d'en voir un
    # apparaître (uv crée `./.venv` au premier `uv run`). Rejoué ici, donc valable aussi pour
    # tout respawn/continue, pas seulement au premier lancement.
    env.update(venv_env.base_venv_env(agent.base_venv))
    return env


class MissingProviderEnvError(RuntimeError):
    """Raised when required provider env vars are missing at agent spawn time."""
    pass


def _required_env_for_model(model: str) -> list[str]:
    """Return list of env var names required for the given model's provider."""
    from ...backend.agent.providers.registry import PROVIDERS
    for _name, prov in PROVIDERS.items():
        if model in prov.get("models", []):
            keys = [prov["api_key_env"]]
            # Anthropic always needs ANTHROPIC_BASE_URL at runtime (gateway endpoint)
            if prov["type"] == "anthropic":
                keys.append("ANTHROPIC_BASE_URL")
            return keys
    # Unknown model — require at least one provider key
    return []


def check_provider_env(model: str, env: dict | None = None) -> None:
    """Raise MissingProviderEnvError if required env vars are absent."""
    env = env if env is not None else os.environ
    required = _required_env_for_model(model)
    missing = [k for k in required if not env.get(k)]
    if missing:
        raise MissingProviderEnvError(
            f"Variables d'environnement manquantes pour le modèle '{model}': {', '.join(missing)}. "
            "Vérifiez que le wrapper d'environnement est actif."
        )


def _server_bouzecode_dir() -> Path:
    """`.bouzecode/` du repo serveur (profils transversaux : monitor/review/...).
    Passé en --extra-dir au spawn pour que les profils se résolvent quel que soit
    le cwd de l'agent (un projet cible n'a pas forcément de profils locaux).

    Même décalage que `_spawn_env` : depuis `runtime/`, la racine du dépôt est `parents[4]`.
    Avec `parents[3]` le chemin rendu était `src/.bouzecode`, qui n'existe pas — l'`--extra-dir`
    ne désignait rien et les profils transversaux ne se résolvaient plus, en silence."""
    return Path(__file__).resolve().parents[4] / ".bouzecode"


def create_agent(prompt: str, model: str, cwd: str, profile: str = "",
                 parent: str = "",
                 ticket_slug: str = "", ticket_id: str = "",
                 run_kind: str = "work", worktree_root: str = "",
                 base_venv: str = "") -> Agent:
    agent_id = uuid.uuid4().hex[:12]
    stdout_path = AGENTS_DIR / f"{agent_id}.out.log"
    session_path = AGENTS_DIR / f"{agent_id}.session.json"
    ipc_dir = AGENTS_DIR / f"{agent_id}.ipc"
    ipc_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        *_bouzecode_launch_cmd(), "-p", "--accept-all", "--loud",
        "--session-file", str(session_path),
        "--web-agent-dir", str(ipc_dir),
    ]
    if model:
        cmd += ["-m", model]
    if profile:
        cmd += ["--profile", profile]
        server_dir = _server_bouzecode_dir()
        if server_dir.is_dir():
            cmd += ["--extra-dir", str(server_dir)]
    cmd.append(prompt)

    # Env guard: fail fast if provider env is incomplete
    check_provider_env(model)

    agent = Agent(
        agent_id=agent_id,
        prompt=prompt,
        model=model,
        cwd=cwd,
        pid=0,
        started_at=datetime.utcnow().isoformat() + "Z",
        stdout_path=str(stdout_path),
        session_path=str(session_path),
        ipc_dir=str(ipc_dir),
        parent=parent,
        ticket_slug=ticket_slug,
        ticket_id=ticket_id,
        run_kind=run_kind or "work",
        profile=profile,
        worktree_root=worktree_root,
        base_venv=base_venv,
    )
    spawn_env = _spawn_env(**_ticket_env(agent))

    stdout_file = stdout_path.open("wb")
    process = subprocess.Popen(
        cmd,
        cwd=cwd or None,
        stdout=stdout_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=spawn_env,
    )
    agent.pid = process.pid
    _save(agent)
    # Un agent VIENT DE NAÎTRE : la page d'arbre déjà calculée ne le contient pas, et le front
    # l'attendait jusqu'à expiration du TTL — 7,9 s mesurées le 2026-08-03 entre l'écriture sur
    # disque et son apparition dans /api/agents/tree, pour une information déjà écrite.
    # Import LOCAL : `services.work.fleet` importe ce module, l'importer en tête ferait un cycle.
    from ..services.work import fleet_cache
    fleet_cache.expire_all()
    return agent


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


# Le classement vit dans web_v2/close_reasons.py — une table unique, lue aussi par
# `wake` et `liveness`. Ici la question est « une livraison est-elle PROUVÉE ? » (rc 0),
# pas « le ticket peut-il avancer ? » : `text_no_tools` avance sans prouver.
_DELIVERY_CLOSE_REASONS = close_reasons.DELIVERY_CLOSE_REASONS


def _ipc_says_graceful(agent: Agent) -> bool:
    """Repli IPC : quand le session JSON ne porte PAS de close_reason gracieux
    (bug racine historique : la session restait close_reason='' à la clôture
    gracieuse), consulter l'état IPC <agent>.ipc/state.json. Gracieux ssi
    status=finished ET close_reason gracieux. status=running ou close_reason
    absent → PAS gracieux (on ne présume rien sans preuve)."""
    ipc_dir = getattr(agent, "ipc_dir", "") or ""
    if not ipc_dir:
        return False
    state = ipc.read_state(ipc.from_dir(ipc_dir))
    if state.get("status") != ipc.STATUS_FINISHED:
        return False
    return state.get("close_reason", "") in _DELIVERY_CLOSE_REASONS


def _returncode_from_session(agent: Agent) -> int:
    """Derive a return code from the disk session's close_reason when the real
    rc is lost (pid gone, Popen not retained). A graceful close (FinalAnswer)
    → 0 ; anything else (api_error, or death without a clean close, or an
    unreadable/absent session) → -1 so web_v2 reports a crash.

    REPLI IPC : si la session ne porte pas de close_reason gracieux (session
    vide/illisible = symptôme du bug racine), on consulte l'IPC en dernier
    ressort — une session vide + IPC=finished:final_answer est une clôture
    GRACIEUSE, pas un crash."""
    import json as _json

    try:
        with open(agent.session_path, "r", encoding="utf-8") as fh:
            data = _json.load(fh)
    except (OSError, ValueError):
        return 0 if _ipc_says_graceful(agent) else -1
    close_reason = data.get("close_reason", "")
    if close_reason in _DELIVERY_CLOSE_REASONS:
        return 0
    return 0 if _ipc_says_graceful(agent) else -1


def refresh_agent_status(agent: Agent) -> Agent:
    """If the process has exited (or IPC says finished), record return code + finished_at."""
    if agent.returncode is not None:
        return agent
    if not psutil.pid_exists(agent.pid):
        agent.finished_at = datetime.utcnow().isoformat() + "Z"
        # The real return code is lost (Popen not retained), so the disk session's
        # close_reason is the source of truth: a non-graceful close (api_error, or
        # any death without FinalAnswer) means the process did NOT finish cleanly →
        # rc=-1 so web_v2 reports a crash instead of a green 'finished'.
        agent.returncode = _returncode_from_session(agent)
        _save(agent)
        return _maybe_drain_deferred(agent)
    try:
        proc = psutil.Process(agent.pid)
        if proc.status() == psutil.STATUS_ZOMBIE:
            agent.finished_at = datetime.utcnow().isoformat() + "Z"
            agent.returncode = proc.wait(timeout=0.1)
            _save(agent)
            return _maybe_drain_deferred(agent)
    except psutil.NoSuchProcess:
        agent.finished_at = datetime.utcnow().isoformat() + "Z"
        agent.returncode = 0
        _save(agent)
        return _maybe_drain_deferred(agent)
    # Process alive but IPC says finished → stuck subprocess, terminate it
    ipc_state = get_ipc_state(agent)
    if ipc_state.get("status") == "finished":
        # Même piège que dans kill_agent : ce pid a pu être recyclé par l'OS et désigner
        # un process TIERS. `terminate_agent_process` exige la preuve d'identité et ne
        # lève pas. Refus ou non, l'agent est marqué fini : son process à LUI est parti.
        terminate_agent_process(agent)
        agent.finished_at = datetime.utcnow().isoformat() + "Z"
        agent.returncode = 0
        _save(agent)
        return _maybe_drain_deferred(agent)
    return agent


def _run_deferred_check(command: str, cwd: str, timeout: int):
    """Run a queued deferred command through the SAME shell wrapper as the Bash tool
    (`_build_popen_command` → PowerShell `-EncodedCommand` on Windows), NEVER cmd.exe.

    Deferred commands are authored as PowerShell (`$env:X = ...; ...`); running them via
    `shell=True` sent them to cmd.exe, which fails instantly on that syntax and never
    executed the check (e.g. the Azure deploy). `_strip_clixml` drops PowerShell's
    module-load progress envelope from stderr; the spilled temp .ps1 (large bodies) is
    removed in `finally`."""
    import contextlib
    from ...backend.tools.ops.shell_search import _build_popen_command, _strip_clixml
    popen_cmd, shell, temp_path = _build_popen_command(command)
    try:
        result = subprocess.run(
            popen_cmd,
            shell=shell,
            cwd=cwd or None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        result.stderr = _strip_clixml(result.stderr or "")
        return result
    finally:
        if temp_path:
            with contextlib.suppress(OSError):
                os.remove(temp_path)


def _maybe_drain_deferred(agent: Agent) -> Agent:
    """After a deferred FinalAnswer the subprocess exits leaving a
    `<session>.deferred.json`. Run each queued check sequentially; all green
    finalizes the close, any failure respawns the agent to fix it."""
    deferred = web_deferred.load(agent.session_path)
    if deferred is None:
        return agent
    checks = deferred.get("checks") or []
    stdout_file = Path(agent.stdout_path).open("ab")
    stdout_file.write(b"\n\n--- Running deferred checks ---\n")
    for check in checks:
        command = check["command"]
        timeout = check.get("timeout") or 600
        stdout_file.write(f"$ {command}\n".encode("utf-8"))
        stdout_file.flush()
        try:
            result = _run_deferred_check(command, agent.cwd, timeout)
        except subprocess.TimeoutExpired:
            stdout_file.write(b"deferred check TIMED OUT\n")
            stdout_file.close()
            error_log = f"Command timed out after {timeout}s: {command}"
            return resume_deferred_agent(agent, error_log)
        stdout_file.write((result.stdout or "").encode("utf-8"))
        stdout_file.write((result.stderr or "").encode("utf-8"))
        stdout_file.flush()
        if result.returncode != 0:
            stdout_file.close()
            error_log = (
                f"Command failed (exit {result.returncode}): {command}\n"
                f"{result.stdout}\n{result.stderr}"
            )
            return resume_deferred_agent(agent, error_log)
    stdout_file.write(b"--- All deferred checks passed ---\n")
    stdout_file.close()
    web_deferred.delete(agent.session_path)
    return agent


def resume_deferred_agent(agent: Agent, error_log: str, model: str = "") -> Agent:
    """Respawn an agent after a deferred check failed, so it can fix and re-emit."""
    agent.auto_retry_count = 0
    return _respawn(
        agent,
        extra_args=["--resume-deferred", error_log],
        banner="\n\n--- Reprise apres echec d un check differe ---\n\n",
        model=model,
    )


_REQUIRED_KEYS = {"agent_id", "prompt", "model", "cwd", "pid", "started_at"}


def _agent_from_dict(data: dict) -> Agent | None:
    """Build Agent from dict, ignoring unknown keys. Returns None if required keys missing."""
    if not _REQUIRED_KEYS.issubset(data):
        return None
    valid = {f.name for f in Agent.__dataclass_fields__.values()}
    return Agent(**{k: v for k, v in data.items() if k in valid})


import time as _time
import threading as _threading

_list_agents_cache: dict = {}
_list_agents_lock = _threading.Lock()
# Un SEUL thread reconstruit la liste à la fois : sans ça, N requêtes concurrentes (le front
# poll toutes les ~1 s) tombant sur un cache expiré relançaient CHACUNE un scan complet de
# ~1000 fichiers → stampede → le serveur passe son temps à recalculer la même liste.
_list_agents_compute_lock = _threading.Lock()
# Cache PERSISTANT par fichier, clé = mtime : un agent `finished` est immuable, on ne relit
# donc JAMAIS son JSON après le 1er chargement (seul un `stat` par fichier subsiste).
_agent_file_cache: dict = {}
_LIST_AGENTS_TTL = 3  # seconds

# Verrous d'idempotence de spawn, un par agent_id. Sous threaded=True, deux threads peuvent
# vouloir respawn le MÊME agent (réveil + action manuelle, retry + resume…) et lancer deux
# process sur le MÊME --session-file → double-spawn (2× tokens, jumeau non-tracké). Le verrou
# sérialise, et le contrôle « un process tourne-t-il déjà pour cette session » ferme la course.
_spawn_locks: dict = {}
_spawn_locks_guard = _threading.Lock()


def _agent_spawn_lock(agent_id: str):
    with _spawn_locks_guard:
        return _spawn_locks.setdefault(agent_id, _threading.Lock())


def list_agents() -> list[Agent]:
    """Return all agents, cached for up to _LIST_AGENTS_TTL seconds (thread-safe).
    Single-flight : un cache expiré ne déclenche qu'UN recalcul, les autres threads
    attendent puis réutilisent son résultat (pas de scan disque en rafale)."""
    now = _time.time()
    with _list_agents_lock:
        if "expires" in _list_agents_cache and now < _list_agents_cache["expires"]:
            return list(_list_agents_cache["data"])
    with _list_agents_compute_lock:
        # Re-check : un thread concurrent a pu rafraîchir le cache pendant qu'on attendait.
        with _list_agents_lock:
            if "expires" in _list_agents_cache and _time.time() < _list_agents_cache["expires"]:
                return list(_list_agents_cache["data"])
        result = _list_agents_uncached()
        with _list_agents_lock:
            _list_agents_cache["data"] = result
            _list_agents_cache["expires"] = _time.time() + _LIST_AGENTS_TTL
        return list(result)


def _list_agents_uncached() -> list[Agent]:
    """Read all agent JSONs from disk + refresh status. Un cache par mtime évite de relire
    et re-parser les fichiers inchangés (l'essentiel : des agents `finished` immuables)."""
    agents: list[Agent] = []
    for path in AGENTS_DIR.glob("*.json"):
        if ".session" in path.stem:  # skip session sidecars (.session/.pending/.deferred .json)
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        key = str(path)
        cached = _agent_file_cache.get(key)
        if cached and cached[0] == mtime:
            agent = cached[1]
        else:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                logging.getLogger(__name__).warning(
                    "Skipping corrupt agent file %s: %s", path, exc
                )
                continue
            agent = _agent_from_dict(data)
            if agent is None:
                continue
            _agent_file_cache[key] = (mtime, agent)
        refresh_agent_status(agent)  # bon marché si terminé (returncode connu → early return)
        agents.append(agent)
    agents.sort(key=lambda a: a.started_at, reverse=True)
    return agents


def is_running(agent: Agent) -> bool:
    return agent.returncode is None and psutil.pid_exists(agent.pid)


def _is_dead_worktree(cwd: str) -> bool:
    """A worktree path (under ~/.bouzecode/worktrees) that no longer holds a `.git` link is
    DEAD: after a merge+reap the folder can survive on disk — readme_sync even repaints a
    solitary AGENTS.md — while the code AND the git link vanished. Popen-ing an agent there
    revives it in an empty dir ('worktree vide' → blocked awaiting_input). os.path.isdir alone
    can't tell this apart from a live checkout, so we key on the worktrees marker + missing .git.
    Only worktree paths are judged: a non-git project runs agents directly in its own dir."""
    parts = Path(cwd).parts
    under_worktrees = ".bouzecode" in parts and "worktrees" in parts
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


def read_stdout(agent: Agent, start: int = 0) -> tuple[str, int]:
    """Return (text_chunk, new_offset) starting at byte offset `start`."""
    path = Path(agent.stdout_path)
    if not path.exists():
        return "", start
    with path.open("rb") as handle:
        handle.seek(start)
        chunk = handle.read()
    return chunk.decode("utf-8", errors="replace"), start + len(chunk)


def _profile_launch_args(profile: str) -> list[str]:
    """Re-inject a resumed agent's `--profile` (and the server extra-dir that carries
    its catalog). WITHOUT this, every resume/respawn boots with NO profile, so
    apply_profile_tools/hooks/skills/plan_mode never run: a read-only manager silently
    regains Edit/Write and starts CODING instead of dispatching. The persona survives
    (loaded from the resumed session) but the TOOL WHITELIST does not — hence the fix."""
    if not profile:
        return []
    args = ["--profile", profile]
    server_dir = _server_bouzecode_dir()
    if server_dir.is_dir():
        args += ["--extra-dir", str(server_dir)]
    return args


def resume_agent(old_agent: Agent, prompt: str, model: str = "") -> Agent:
    """Spawn a new agent that resumes from an existing agent's session."""
    agent_id = uuid.uuid4().hex[:12]
    stdout_path = AGENTS_DIR / f"{agent_id}.out.log"
    session_path = AGENTS_DIR / f"{agent_id}.session.json"
    ipc_dir = AGENTS_DIR / f"{agent_id}.ipc"
    ipc_dir.mkdir(parents=True, exist_ok=True)

    use_model = model or old_agent.model
    cmd = [*_bouzecode_launch_cmd(), "-p", "--accept-all"]
    if use_model:
        cmd += ["-m", use_model]
    cmd += _profile_launch_args(old_agent.profile)
    cmd += [
        "--session-file", str(session_path),
        "--resume-from", old_agent.session_path,
        "--web-agent-dir", str(ipc_dir),
        prompt,
    ]

    stdout_file = stdout_path.open("wb")
    process = subprocess.Popen(
        cmd,
        cwd=_safe_cwd(old_agent.cwd),
        stdout=stdout_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=_spawn_env(),
    )

    agent = Agent(
        agent_id=agent_id,
        prompt=prompt,
        model=use_model,
        cwd=old_agent.cwd,
        pid=process.pid,
        started_at=datetime.utcnow().isoformat() + "Z",
        stdout_path=str(stdout_path),
        session_path=str(session_path),
        ipc_dir=str(ipc_dir),
        parent=old_agent.parent,
        profile=old_agent.profile,
    )
    _save(agent)
    return agent


def _respawn(agent: Agent, extra_args: list[str], banner: str, model: str = "") -> "Agent | None":
    """Shared respawn logic: clean IPC, launch subprocess, update agent state.

    Ré-utilise le MÊME --session-file (contrairement à resume_agent qui en crée un neuf) →
    seul point où deux threads peuvent lancer un jumeau sur une même session. Sérialisé par
    _agent_spawn_lock + garde d'idempotence (double-spawn évité à la racine)."""
    use_model = model or agent.model
    with _agent_spawn_lock(agent.agent_id):
        # Un process tourne déjà pour cette session (autre thread ayant respawné pendant l'attente
        # du verrou, ou précédent non encore mort) → NE PAS lancer de jumeau (2× tokens).
        if _session_process_running(agent.session_path):
            logging.getLogger(__name__).warning(
                "respawn ignoré (double-spawn évité) : process déjà vivant pour %s",
                agent.session_path)
            return None  # respawn NON effectué → l'appelant (continue_coder) ne doit
            # PAS enregistrer de run 'work' fantôme qui brûlerait le plafond de passes.

        if agent.ipc_dir:
            ipc_path = Path(agent.ipc_dir)
            for f in ipc_path.iterdir():
                try:
                    f.unlink()
                except OSError:
                    pass

        cmd = [*_bouzecode_launch_cmd(), "-p", "--accept-all"]
        if use_model:
            cmd += ["-m", use_model]
        cmd += _profile_launch_args(agent.profile)
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
            env=_spawn_env(**_ticket_env(agent)),
        )

        agent.pid = process.pid
        agent.model = use_model
        agent.finished_at = ""
        agent.returncode = None
        _save(agent)
        return agent


def _session_has_persisted_turn(session_path: str) -> bool:
    """True ssi la session JSON existe et contient au moins un tour persisté.

    Tolère l'absence de fichier, un fichier vide ou un JSON invalide → False. Sert à
    distinguer un « reprendre » sur un agent qui n'a jamais persisté de tour (crash très
    précoce, reboot forcé) — où il faut REJOUER le prompt d'origine du ticket — d'un
    continue normal sur une session vivante — où le texte donné doit être transmis."""
    try:
        with open(session_path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except (OSError, FileNotFoundError):
        return False
    if not raw.strip():
        return False
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return False
    return bool(data.get("messages"))


def _is_warm(agent: Agent) -> bool:
    """True ssi le process de l'agent est ENCORE VIVANT et reprenable à chaud.

    Warm = pid vivant + IPC status 'idle' OU 'finished' : le process bouzecode
    tourne toujours dans son run_agent_event_loop (keep_warm). 'idle' = il poll
    déjà followup.txt. 'finished' = FENÊTRE transitoire post-FinalAnswer : le tour
    a stampé l'IPC FINISHED (via _fire_completion) et le on_completion/test-gate
    peut bloquer jusqu'à ~1900s AVANT que la warm loop ne réécrive 'idle'. Pendant
    cette fenêtre le pid est vivant : refuser la reprise chaude condamnait le
    follow-up à un TROU NOIR — ni chaud (status≠idle) ni froid (_respawn refuse un
    pid vivant via sa garde anti-double-spawn) → clic « Envoyer » sans effet ni
    erreur. Pousser followup.txt marche : la warm loop le pop dès on_completion fini.
    On peut donc reprendre IN-PROCESS (push followup.txt) sans cold-start respawn."""
    if not agent.pid or not agent.ipc_dir:
        return False
    if not psutil.pid_exists(agent.pid):
        return False
    return get_ipc_state(agent).get("status") in ("idle", "finished")


is_warm = _is_warm  # alias public (fleet._node badge 'chaud')


def _push_followup(agent: Agent, prompt: str) -> Agent:
    """Reprise CHAUDE : pousse le prompt dans followup.txt du process vivant.

    Le run_agent_event_loop idle du process va pop_text(followup) et exécuter le
    tour DANS LE MÊME PROCESS (zéro cold-start). On reset finished_at/returncode
    pour que web_v2 cesse de le voir 'terminé'."""
    paths = ipc.from_dir(agent.ipc_dir)
    # Un nouveau tour demandé par l'utilisateur ANNULE toute interruption pendante :
    # sinon un cancel.flag laissé par un /interrupt précédent (le process est resté vivant/idle,
    # pas de cold-respawn qui purge l'IPC) est consommé dès le 1er point d'interruption du tour
    # relancé → l'agent « s'interromp en permanence malgré les messages et les relances ».
    ipc.consume_cancel(paths)
    paths.followup.write_text(prompt, encoding="utf-8")
    agent.finished_at = ""
    agent.returncode = None
    _save(agent)
    return agent


def _is_warm_awaiting(agent: Agent) -> bool:
    """True ssi le process est vivant ET en pause question (awaiting_input/plan)."""
    if not agent.pid or not agent.ipc_dir:
        return False
    if not psutil.pid_exists(agent.pid):
        return False
    return get_ipc_state(agent).get("status") in ("awaiting_input", "awaiting_plan_validation")


def is_mid_turn(agent: Agent) -> bool:
    """L'agent joue-t-il ENCORE un tour ? (par opposition à : il a cédé)

    `is_running` — pid vivant — répond à une AUTRE question, et c'est celle-là que
    `/interrupt` posait pour décider d'escalader vers le kill. Or un agent chaud est CONÇU
    pour survivre à son tour : `ipc.run_agent_event_loop` écrit `idle` puis sonde
    `followup.txt`, process résident. Son pid existait donc toujours après une annulation
    PARFAITEMENT réussie → l'escalade le tuait à TOUS LES COUPS, et le message suivant
    repartait en cold-respawn (process neuf, imports, contexte réémis) là où un simple
    `_push_followup` sur le process vivant aurait suffi. C'est ce qui rendait une
    interruption web lente là où le Ctrl+C du TUI est immédiat.

    Céder, c'est ne plus tenir le tour, de quelque façon que ce soit : process parti,
    retombé oisif (`_is_warm`), ou mis en pause sur une question (`_is_warm_awaiting`) —
    les trois états dans lesquels on peut de nouveau lui parler."""
    if not is_running(agent):
        return False
    return not (_is_warm(agent) or _is_warm_awaiting(agent))


def _push_answer(agent: Agent, answer: str) -> Agent:
    """Reprise CHAUDE d'une pause question : pousse la réponse dans answer.txt."""
    paths = ipc.from_dir(agent.ipc_dir)
    # Symétrique de _push_followup : une reprise chaude d'AskUserQuestion doit purger un
    # cancel.flag pendant, sinon le tour relancé s'auto-interrompt aussitôt (boucle).
    ipc.consume_cancel(paths)
    paths.answer.write_text(answer, encoding="utf-8")
    agent.finished_at = ""
    agent.returncode = None
    _save(agent)
    return agent


# Prompt de reprise injecté quand « Reprendre » relance une session AVEC tours mais sans
# nouveau texte (POST {text:""}). Un positionnel vide tuerait le CLI (-p + prompt vide →
# cli.py sys.exit(1)). Ce prompt non vide passe le guard ET relance un vrai tour de reprise.
RESUME_PROMPT = "Reprends la tâche interrompue là où elle s'est arrêtée."


def continue_agent(agent: Agent, prompt: str, model: str = "") -> "Agent | None":
    """Respawn a finished agent as the same session (same ID, logs, IPC).

    Renvoie l'agent respawné, ou None si le respawn a été ignoré (garde anti-double-spawn :
    un process est encore vivant pour cette session). Les appelants qui enregistrent un run
    (continue_coder) DOIVENT ne le faire QUE si le respawn a réellement eu lieu.

    Cas « reprendre » (bouton UI, prompt vide OU session jamais persistée) : si la session
    n'a AUCUN tour persisté (agent crashé avant d'écrire quoi que ce soit, p.ex. reboot
    forcé), on IGNORE `prompt` et on rejoue le prompt d'origine du ticket (`agent.prompt`) —
    sinon l'agent est relancé avec un texte vide/parasite et « ne reprend rien »."""
    agent.auto_retry_count = 0
    # Reprise CHAUDE : si le process est encore vivant (idle), on pousse le prompt
    # dans followup.txt et le tour est exécuté IN-PROCESS — pas de cold-start respawn.
    # (skip si un model override est demandé : il faut alors un nouveau process.)
    if not model and _is_warm(agent):
        return _push_followup(agent, prompt)
    # Reprise FROIDE : process mort → respawn. Si la session n'a AUCUN tour persisté
    # (crash très précoce / reboot forcé), on rejoue le prompt d'origine du ticket.
    if _session_has_persisted_turn(agent.session_path):
        # Le bouton « Reprendre » POST {text:""} → prompt vide. Sur une session AVEC tours,
        # passer "" au CLI (`-p ... --resume-from <s> ""`) faisait argparse→prompt=[""]→
        # initial=""→ cli.py `if print_mode and not initial: sys.exit(1)` : le process
        # mourait AUSSITÔT sans jouer de tour → « Reprendre ne relance rien ». On substitue
        # un prompt de reprise non vide qui passe le guard ET relance un vrai tour.
        effective = prompt or RESUME_PROMPT
    else:
        effective = agent.prompt
    return _respawn(
        agent,
        extra_args=[effective],
        banner=f"\n\n--- Session continued ---\n\n\u00bb {effective}\n\n",
        model=model,
    )


def resume_pending_agent(agent: Agent, answer: str, model: str = "") -> "Agent | None":
    """Respawn a paused agent to consume `<session>.pending.json` with the answer.

    Rend `None` — comme `continue_agent` — quand `_respawn` a REFUSÉ de lancer (un process
    tourne déjà pour cette session) : la réponse n'a alors PAS été remise, et l'appelant doit
    le dire au lieu de conclure au succès."""
    # Reprise CHAUDE d'une pause : process vivant en awaiting → push answer.txt in-process.
    if not model and _is_warm_awaiting(agent):
        return _push_answer(agent, answer)
    agent.auto_retry_count = 0
    return _respawn(
        agent,
        extra_args=["--resume-pending", answer],
        banner=f"\n\n--- Resuming from AskUserQuestion ---\n\u00bb {answer}\n\n",
        model=model,
    )


def resume_auto_agent(agent: Agent, model: str = "") -> Agent:
    """Respawn a crashed agent to complete pending tool_calls without injecting a user message."""
    agent.auto_retry_count += 1
    return _respawn(
        agent,
        extra_args=["--resume-auto"],
        banner=f"\n\n--- Resuming auto (retry #{agent.auto_retry_count}) ---\n\n",
        model=model,
    )


def _session_has_pending_tool_calls(session_path: str) -> bool:
    """True if the saved session ends on an assistant msg with unresolved tool_calls."""
    path = Path(session_path)
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    messages = data.get("messages", [])
    last_asst_idx = next(
        (i for i in range(len(messages) - 1, -1, -1)
         if messages[i].get("role") == "assistant"),
        None,
    )
    if last_asst_idx is None:
        return False
    tcs = messages[last_asst_idx].get("tool_calls") or []
    if not tcs:
        return False
    resolved = {m.get("tool_call_id") for m in messages[last_asst_idx + 1:]
                if m.get("role") == "tool"}
    return any(tc["id"] not in resolved for tc in tcs)


def _session_interrupted_after_user_msg(session_path: str) -> bool:
    """True if the agent crashed having emitted only an opening assistant message
    (no tool_calls) directly after the user prompt — interrupted mid-thinking
    before doing any work, so the turn never completed. A session that ran a tool
    cycle and produced a concluding answer ends with the assistant msg following a
    `tool` result, not the `user` msg, and is treated as resolved (not resumed)."""
    path = Path(session_path)
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    messages = data.get("messages", [])
    if len(messages) < 2 or messages[-1].get("role") != "assistant":
        return False
    if messages[-1].get("tool_calls"):
        return False  # pending tool_calls are handled by the check above
    return messages[-2].get("role") == "user"


_ipc_state_cache: dict = {}  # ipc_dir -> (mtime, state) : évite de relire le fichier IPC de
# CHAQUE agent à chaque construction du tree/compteurs (961 lectures/requête). Un agent fini a
# un IPC stable → jamais relu ; un agent actif change de mtime → relu.


def get_ipc_state(agent: Agent) -> dict:
    if not agent.ipc_dir:
        return {"status": "unknown"}
    paths = ipc.from_dir(agent.ipc_dir)
    try:
        mtime = paths.state.stat().st_mtime
    except OSError:
        return ipc.read_state(paths)  # fichier absent → défaut géré par read_state
    cached = _ipc_state_cache.get(agent.ipc_dir)
    if cached and cached[0] == mtime:
        return cached[1]
    state = ipc.read_state(paths)
    _ipc_state_cache[agent.ipc_dir] = (mtime, state)
    return state


def reconcile_dead_agents() -> list[str]:
    """Démarrage web_v2 : stampe finished_at/returncode sur les agents au pid MORT mais non
    clôturés (crash/kill/redémarrage serveur). Sans ça, ces « zombies » se font réconcilier
    LAZY dans le chemin chaud `list_agents` — 99 `_save` sous contention du poller (retry
    WinError) tenant le compute-lock → tout /api/projects+/tree wedge (timeout 180 s observé).
    Réconcilie UNIQUEMENT (pas d'auto-retry/respawn : web_v2 pilote la reprise via son wake).
    Mono-thread au boot (aucun poller/requête concurrent) → pas de course fichier. Renvoie la
    LISTE des agent_ids stampés rc=-1 à CE boot (agents crashés à signaler dans le rapport des
    interrompus). Un agent légitimement `awaiting_input` garde son statut IPC (returncode 0,
    IPC intact) donc reste affiché « en attente » et n'est PAS dans la liste."""
    crashed_ids: list[str] = []
    for path in AGENTS_DIR.glob("*.json"):
        if ".session" in path.stem:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        agent = _agent_from_dict(data)
        if agent is None or agent.returncode is not None:
            continue
        if psutil.pid_exists(agent.pid):
            continue
        agent.finished_at = datetime.utcnow().isoformat() + "Z"
        ipc_status = get_ipc_state(agent).get("status")
        # Agent en ATTENTE utilisateur (awaiting_input / awaiting_plan_validation) :
        # jamais crashé, rc=0 (comportement conservé). Pour tout le reste on délègue
        # à _returncode_from_session — MÊME source de vérité que le chemin CHAUD
        # (refresh_agent_status) : le close_reason disque fait foi. Sans ça, un agent
        # clos GRACIEUSEMENT sur `final_answer_deferred` (dont l'IPC n'est pas resté
        # `finished` pendant le drain deferred) était faussement stampé rc=-1 → listé
        # « crashed » dans le rapport des interrompus → faux bandeau « Cet agent a été
        # interrompu. Reprendre ? ». _returncode_from_session le classe rc=0 (gracieux).
        if ipc_status in ("awaiting_input", "awaiting_plan_validation"):
            agent.returncode = 0
        else:
            agent.returncode = _returncode_from_session(agent)
        _save(agent)
        if agent.returncode == -1:
            crashed_ids.append(agent.agent_id)
    return crashed_ids


def resume_interrupted_agents() -> list[Agent]:
    """Called at Flask startup. Mark dead agents as finished, then auto-retry
    the genuinely crashed ones that have unresolved tool_calls via
    `resume_auto_agent` (capped by `_MAX_AUTO_RETRIES`, skipped if the user had
    manually killed the agent — signaled by a leftover `cancel.flag`)."""
    resumed: list[Agent] = []
    for path in AGENTS_DIR.glob("*.json"):
        if ".session" in path.stem:  # skip session sidecars (.session/.pending/.deferred .json)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        agent = _agent_from_dict(data)
        if agent is None or agent.returncode is not None:
            continue
        if psutil.pid_exists(agent.pid):
            continue
        agent.finished_at = datetime.utcnow().isoformat() + "Z"
        ipc_state = get_ipc_state(agent)
        ipc_status = ipc_state.get("status")
        agent.returncode = 0 if ipc_status in ("finished", "awaiting_input", "awaiting_plan_validation") else -1
        if agent.ipc_dir and ipc_status not in ("finished", "awaiting_input", "awaiting_plan_validation"):
            ipc.write_state(ipc.from_dir(agent.ipc_dir), ipc.STATUS_FINISHED)
        _save(agent)

        if agent.returncode != -1:
            continue
        if agent.auto_retry_count >= _MAX_AUTO_RETRIES:
            continue
        if agent.ipc_dir and (Path(agent.ipc_dir) / "cancel.flag").exists():
            continue
        if not agent.session_path:
            continue
        if not (_session_has_pending_tool_calls(agent.session_path)
                or _session_interrupted_after_user_msg(agent.session_path)):
            continue  # session fully resolved — nothing left to resume
        resume_auto_agent(agent)
        resumed.append(agent)
    return resumed


def _procs_for_session(session_path: str):
    """Yield live python processes whose command line references `session_path` (unique per
    agent). Autorité disque/OS, indépendante du pid en mémoire — base du reap ET de la garde
    d'idempotence de spawn."""
    if not session_path:
        return
    for proc in psutil.process_iter(["name", "cmdline"]):
        if not str(proc.info.get("name") or "").lower().startswith("python"):
            continue
        if any(session_path in str(arg) for arg in (proc.info.get("cmdline") or [])):
            yield proc


def _session_process_running(session_path: str) -> bool:
    """Un process est-il DÉJÀ vivant pour cette session ? (garde anti double-spawn au respawn)."""
    return any(proc.is_running() for proc in _procs_for_session(session_path))


# Alias public : c'est la SEULE preuve de vivacité qui ne dépende ni du pid tracké (recyclable)
# ni des champs `returncode`/`finished_at` du .json (écrits par un autre process, donc
# possiblement périmés). `purge` s'en sert avant de déplacer le moindre artefact.
session_process_running = _session_process_running


def reap_session_processes(session_path: str) -> int:
    """Terminate every python process whose command line references `session_path`.

    A double-spawn leaves an untracked TWIN process (same ``--session-file``) that
    `kill_agent` — which knows only the last tracked pid — cannot reach; it keeps looping
    and burning tokens after the ticket merged. Called on integration to reap the twin.
    Matching on the (unique per agent) session-file path never touches an unrelated
    process. Returns the number of processes terminated."""
    killed = 0
    for proc in _procs_for_session(session_path):
        if proc.is_running() and not signal_termination(proc):
            continue  # refus de l'OS sur CE process : les jumeaux suivants y ont droit
        killed += 1
    return killed


def signal_termination(proc, agent: "Agent | None" = None) -> bool:
    """Envoie `terminate()` et fait du REFUS DE L'OS un résultat, jamais une panne.

    `psutil.AccessDenied` sur un pid est un cas COURANT sous Windows : process en train de
    mourir, pid recyclé par un process d'une autre session, ACL. Il remontait jusqu'ici tel
    quel — donc jusqu'à `refresh_agent_status`, appelé par CHAQUE `list_agents()`, c'est-à-dire
    par presque toutes les routes : un seul pid intouchable et le serveur entier répondait 500
    (incident du 28/07, trois /interrupt d'affilée).

    Rien n'est avalé : le motif est journalisé ET inscrit sur l'agent (`termination_error`,
    servi par l'API), et remis à "" dès qu'une terminaison aboutit."""
    try:
        proc.terminate()
    except (psutil.Error, OSError) as exc:
        motif = f"{type(exc).__name__} (pid={getattr(proc, 'pid', '?')})"
        logging.getLogger(__name__).warning(
            "terminaison refusée par l'OS : %s — l'agent reste vivant", motif)
        if agent is not None:
            agent.termination_error = motif
            _save(agent)
        return False
    if agent is not None and agent.termination_error:
        agent.termination_error = ""
        _save(agent)
    return True


def destruction_permitted() -> bool:
    """False sous pytest : aucun test ne doit pouvoir DÉTRUIRE quoi que ce soit.

    Couvre les deux gestes irréversibles du serveur : terminer un process
    (`terminate_agent_process`, `fleet.sweep_warm_pool`) et déplacer les artefacts d'un
    agent hors du parc (`purge.purge_agents`). Les deux ont frappé de la production
    réelle le 2026-07-28 depuis la suite de tests.

    Détecter l'environnement de test depuis du code de production est un compromis
    assumé. Il est le bon ICI, et seulement ici, pour quatre raisons mesurées :
      * la protection concurrente (isoler le parc dans les conftests) est de la
        DISCIPLINE — et c'est précisément elle qui a cédé : l'opt-out existait déjà
        (`BOUZECODE_WAKE_POLLER`) mais le conftest posait un AUTRE nom, si bien que le
        poller tournait quand même et envoyait des centaines de `terminate()` ;
      * la discipline a cédé une SECONDE fois, et plus gravement : avant le 2026-07-28
        14:16, aucun conftest ne redirigeait `AGENTS_DIR`, `TRASH_DIR` ni `DELETED_PATH`.
        Le registre de production en porte encore la trace — quatre agents de FIXTURE
        (`parent`, `child1`, `child2`, `cccccc`) écrits dedans par la suite ;
      * le garde est UNIDIRECTIONNEL : il ne peut que REFUSER une destruction, jamais en
        provoquer une. Son pire coût en production est une éviction ou une purge manquée ;
      * `PYTEST_CURRENT_TEST` est posé par pytest LUI-MÊME dans le process qui exécute
        le test. Le serveur web_v2 est lancé par `bouzeui.ps1`, jamais par pytest : il
        n'existe pas de faux positif réaliste en exploitation.
    Le garde reste par ailleurs une couture : un test peut le neutraliser explicitement
    quand il veut prouver le comportement réel (`autoriser_la_destruction`)."""
    return "PYTEST_CURRENT_TEST" not in os.environ


def _pid_still_belongs_to(agent: Agent) -> bool:
    """Le pid tracké désigne-t-il ENCORE le process de cet agent ?

    Un pid est RECYCLÉ par l'OS dès que son process meurt : le pid d'un agent terminé
    désigne, quelques heures plus tard, un process TIERS arbitraire. C'est ce qui a été
    observé — un `terminate()` refusé par les ACL Windows sur un pid qui n'appartenait
    plus à l'agent depuis longtemps. `AccessDenied` ne disait pas « le système protège
    l'agent » mais « ce pid n'est plus le sien ».

    Preuve retenue : la COMMAND LINE doit encore référencer le `--session-file` de
    l'agent (unique par agent) — la même autorité OS que `_procs_for_session`. Mesuré
    sous Windows avec psutil 7.2.2 sur ce poste :
      * `cmdline()` est LISIBLE pour nos propres agents (même utilisateur) et lève
        `AccessDenied` sur les process système/d'un autre utilisateur — c'est-à-dire
        exactement ceux qu'il ne faut JAMAIS tuer : le refus est fail-safe ;
      * `create_time()` est, lui, lisible sur TOUS les process, mais il n'existe aucune
        référence à laquelle le comparer : `_respawn` réassigne `agent.pid` SANS
        rafraîchir `started_at`, donc un agent légitimement respawné a un `create_time`
        postérieur de plusieurs heures à son `started_at`. Comparer les deux refuserait
        de tuer de vrais agents — un garde qui ne garde rien.
    Sans `session_path` (agent hors spawn normal), aucune preuve n'est possible → False."""
    if not agent.session_path:
        return False
    try:
        cmdline = psutil.Process(agent.pid).cmdline() or []
    except (psutil.Error, OSError):
        return False  # pid disparu, ou process d'autrui : dans les deux cas, pas le nôtre
    return any(agent.session_path in str(arg) for arg in cmdline)


def terminate_agent_process(agent: Agent) -> bool:
    """UNIQUE porte vers `terminate()` sur `agent.pid`. True ssi le signal a été envoyé.

    Ne lève jamais : un échec d'identité n'est pas une erreur d'appelant, c'est le
    fonctionnement normal du garde. Il est tracé, jamais avalé en silence."""
    if not destruction_permitted():
        return False
    if agent.returncode is not None or agent.finished_at:
        # Agent DÉJÀ terminé : son pid est libre depuis longtemps et a pu être recyclé.
        # Il n'est candidat à aucune terminaison, quelle que soit la politique appelante.
        return False
    if not agent.pid or not psutil.pid_exists(agent.pid):
        return False
    if not _pid_still_belongs_to(agent):
        logging.getLogger(__name__).warning(
            "terminate refusé : le pid %s n'appartient plus à l'agent %s (pid recyclé)",
            agent.pid, agent.agent_id)
        return False
    return signal_termination(psutil.Process(agent.pid), agent)


def kill_agent(agent: Agent) -> dict:
    """Tue l'agent et REND COMPTE : `{signalled, error, twins}`.

    `error` n'est renseigné que sur un REFUS de l'OS (le seul cas où l'agent est toujours
    là alors qu'on a demandé son arrêt) ; `signalled=False` avec `error` vide veut dire
    qu'il n'y avait rien à tuer (déjà fini, pid recyclé, terminaison interdite sous pytest).
    L'appelant peut ainsi dire la vérité à l'utilisateur au lieu de prétendre un succès."""
    if agent.ipc_dir:
        paths = ipc.from_dir(agent.ipc_dir)
        paths.cancel.write_text("", encoding="utf-8")
    signalled = terminate_agent_process(agent)
    # kill_agent ne connaît que le DERNIER pid tracké ; un twin double-spawn (même
    # --session-file, autre pid) survivrait. reap_session_processes le rattrape via
    # l'autorité OS (cmdline). session_path vide → reap renvoie 0 (no-op sûr).
    session_path = getattr(agent, "session_path", None)
    twins = reap_session_processes(session_path) if session_path else 0
    refresh_agent_status(agent)
    # Un agent qu'on arrête n'attend plus de réponse : son marqueur de question pendante
    # doit partir AVEC lui, sinon il continue d'annoncer une attente que personne n'honorera
    # (cas vécu : `63cd2c4183e8`, tué, listé « attend une réponse » le lendemain).
    # `pending.cancel` est le geste JUSTE — il injecte un `(cancelled by user)` pour les
    # tool_calls restés sans résultat, donc la session demeure valide pour l'API, là où un
    # simple effacement la laisserait avec un tool_call orphelin. Seulement si l'agent est
    # bien arrêté : tant qu'il respire, sa pause lui appartient.
    if session_path and not is_running(agent):
        web_pending.cancel(session_path)
    return {"signalled": signalled, "twins": twins,
            "error": getattr(agent, "termination_error", "") or ""}


def graceful_cancel_agent(agent: Agent) -> None:
    """Write cancel.flag WITHOUT terminating — gives the subprocess time to save."""
    if agent.ipc_dir:
        paths = ipc.from_dir(agent.ipc_dir)
        paths.cancel.write_text("", encoding="utf-8")
