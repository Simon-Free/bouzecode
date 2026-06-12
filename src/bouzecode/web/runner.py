# [desc] Spawns, persists, and tracks bouzecode_sncf CLI subprocess agents with status refresh. [/desc]
"""Spawn and track bouzecode_sncf subprocess agents."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import psutil

from ..web import ipc


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


def _agent_json_path(agent_id: str) -> Path:
    return AGENTS_DIR / f"{agent_id}.json"


def _save(agent: Agent) -> None:
    _agent_json_path(agent.agent_id).write_text(
        json.dumps(asdict(agent), indent=2), encoding="utf-8"
    )


def _bouzecode_launch_cmd() -> list[str]:
    """Launch bouzecode via `python -m bouzecode` — avoids Windows .exe shim file locks.
    -P (PYTHONSAFEPATH) : le cwd de l'agent ne doit pas pouvoir shadower le package
    bouzecode (ex. projet avec un bouzecode.py racine, comme bouzecode_oss)."""
    return [sys.executable, "-P", "-m", "bouzecode"]


def _spawn_env(**extra: str) -> dict:
    """Env des agents spawnés : le package bouzecode du serveur doit gagner quel que
    soit le cwd (avec -P, le cwd sort de sys.path ; PYTHONPATH garantit la résolution)."""
    pkg_root = str(Path(__file__).resolve().parents[2])
    previous = os.environ.get("PYTHONPATH", "")
    pythonpath = pkg_root + (os.pathsep + previous if previous else "")
    return {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": pythonpath,
        **extra,
    }


class MissingProviderEnvError(RuntimeError):
    """Raised when required provider env vars are missing at agent spawn time."""
    pass


def _required_env_for_model(model: str) -> list[str]:
    """Return list of env var names required for the given model's provider."""
    from ..backend.agent.providers.registry import PROVIDERS
    for _name, prov in PROVIDERS.items():
        if model in prov.get("models", []):
            keys = [prov["api_key_env"]]
            # Anthropic always needs ANTHROPIC_BASE_URL at runtime (SNCF socle)
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
            "Vérifiez que le wrapper d'env SNCF est actif."
        )


def create_agent(prompt: str, model: str, cwd: str, profile: str = "", paralysis_abort_after: int | None = None) -> Agent:
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
    cmd.append(prompt)

    # Env guard: fail fast if provider env is incomplete
    check_provider_env(model)

    # Paralysis abort: default 0 for web (human/supervisor can kill), bench keeps 12
    abort_val = 0 if paralysis_abort_after is None else paralysis_abort_after
    spawn_env = _spawn_env(BOUZECODE_PARALYSIS_ABORT_AFTER=str(abort_val))

    stdout_file = stdout_path.open("wb")
    process = subprocess.Popen(
        cmd,
        cwd=cwd or None,
        stdout=stdout_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=spawn_env,
    )

    agent = Agent(
        agent_id=agent_id,
        prompt=prompt,
        model=model,
        cwd=cwd,
        pid=process.pid,
        started_at=datetime.utcnow().isoformat() + "Z",
        stdout_path=str(stdout_path),
        session_path=str(session_path),
        ipc_dir=str(ipc_dir),
    )
    _save(agent)
    return agent


def load_agent(agent_id: str) -> Agent | None:
    path = _agent_json_path(agent_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return _agent_from_dict(data)


def refresh_agent_status(agent: Agent) -> Agent:
    """If the process has exited (or IPC says finished), record return code + finished_at."""
    if agent.returncode is not None:
        return agent
    if not psutil.pid_exists(agent.pid):
        agent.finished_at = datetime.utcnow().isoformat() + "Z"
        agent.returncode = 0
        _save(agent)
        return agent
    try:
        proc = psutil.Process(agent.pid)
        if proc.status() == psutil.STATUS_ZOMBIE:
            agent.finished_at = datetime.utcnow().isoformat() + "Z"
            agent.returncode = proc.wait(timeout=0.1)
            _save(agent)
            return agent
    except psutil.NoSuchProcess:
        agent.finished_at = datetime.utcnow().isoformat() + "Z"
        agent.returncode = 0
        _save(agent)
        return agent
    # Process alive but IPC says finished → stuck subprocess, terminate it
    ipc_state = get_ipc_state(agent)
    if ipc_state.get("status") == "finished":
        try:
            psutil.Process(agent.pid).terminate()
        except psutil.NoSuchProcess:
            pass
        agent.finished_at = datetime.utcnow().isoformat() + "Z"
        agent.returncode = 0
        _save(agent)
    return agent


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
_LIST_AGENTS_TTL = 3  # seconds


def list_agents() -> list[Agent]:
    """Return all agents, cached for up to _LIST_AGENTS_TTL seconds (thread-safe)."""
    now = _time.time()
    with _list_agents_lock:
        if "expires" in _list_agents_cache and now < _list_agents_cache["expires"]:
            return list(_list_agents_cache["data"])
    # Cache miss — compute outside lock to avoid blocking
    result = _list_agents_uncached()
    with _list_agents_lock:
        _list_agents_cache["data"] = result
        _list_agents_cache["expires"] = _time.time() + _LIST_AGENTS_TTL
    return result


def _list_agents_uncached() -> list[Agent]:
    """Read all agent JSONs from disk + refresh status."""
    agents: list[Agent] = []
    for path in AGENTS_DIR.glob("*.json"):
        if path.stem.endswith(".session"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        agent = _agent_from_dict(data)
        if agent is None:
            continue
        refresh_agent_status(agent)
        agents.append(agent)
    agents.sort(key=lambda a: a.started_at, reverse=True)
    return agents


def is_running(agent: Agent) -> bool:
    return agent.returncode is None and psutil.pid_exists(agent.pid)


def read_stdout(agent: Agent, start: int = 0) -> tuple[str, int]:
    """Return (text_chunk, new_offset) starting at byte offset `start`."""
    path = Path(agent.stdout_path)
    if not path.exists():
        return "", start
    with path.open("rb") as handle:
        handle.seek(start)
        chunk = handle.read()
    return chunk.decode("utf-8", errors="replace"), start + len(chunk)


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
    cmd += [
        "--session-file", str(session_path),
        "--resume-from", old_agent.session_path,
        "--web-agent-dir", str(ipc_dir),
        prompt,
    ]

    stdout_file = stdout_path.open("wb")
    process = subprocess.Popen(
        cmd,
        cwd=old_agent.cwd or None,
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
    )
    _save(agent)
    return agent


def _respawn(agent: Agent, extra_args: list[str], banner: str, model: str = "") -> Agent:
    """Shared respawn logic: clean IPC, launch subprocess, update agent state."""
    use_model = model or agent.model

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
        cwd=agent.cwd or None,
        stdout=stdout_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=_spawn_env(),
    )

    agent.pid = process.pid
    agent.model = use_model
    agent.finished_at = ""
    agent.returncode = None
    _save(agent)
    return agent


def continue_agent(agent: Agent, prompt: str, model: str = "") -> Agent:
    """Respawn a finished agent as the same session (same ID, logs, IPC)."""
    agent.auto_retry_count = 0
    return _respawn(
        agent,
        extra_args=[prompt],
        banner=f"\n\n--- Session continued ---\n\n\u00bb {prompt}\n\n",
        model=model,
    )


def resume_pending_agent(agent: Agent, answer: str, model: str = "") -> Agent:
    """Respawn a paused agent to consume `<session>.pending.json` with the answer."""
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


def get_ipc_state(agent: Agent) -> dict:
    if not agent.ipc_dir:
        return {"status": "unknown"}
    paths = ipc.from_dir(agent.ipc_dir)
    return ipc.read_state(paths)


def resume_interrupted_agents() -> list[Agent]:
    """Called at Flask startup. Mark dead agents as finished, then auto-retry
    the genuinely crashed ones that have unresolved tool_calls via
    `resume_auto_agent` (capped by `_MAX_AUTO_RETRIES`, skipped if the user had
    manually killed the agent — signaled by a leftover `cancel.flag`)."""
    resumed: list[Agent] = []
    for path in AGENTS_DIR.glob("*.json"):
        if path.stem.endswith(".session"):
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


def kill_agent(agent: Agent) -> None:
    if agent.ipc_dir:
        paths = ipc.from_dir(agent.ipc_dir)
        paths.cancel.write_text("", encoding="utf-8")
    if psutil.pid_exists(agent.pid):
        psutil.Process(agent.pid).terminate()
    refresh_agent_status(agent)


def graceful_cancel_agent(agent: Agent) -> None:
    """Write cancel.flag WITHOUT terminating — gives the subprocess time to save."""
    if agent.ipc_dir:
        paths = ipc.from_dir(agent.ipc_dir)
        paths.cancel.write_text("", encoding="utf-8")
