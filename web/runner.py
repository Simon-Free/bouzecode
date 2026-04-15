# [desc] Spawns, persists, and tracks bouzecode CLI subprocess agents with status refresh. [/desc]
"""Spawn and track bouzecode subprocess agents."""
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

from web import ipc


AGENTS_DIR = Path.home() / ".bouzecode" / "web_agents"
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


def _agent_json_path(agent_id: str) -> Path:
    return AGENTS_DIR / f"{agent_id}.json"


def _save(agent: Agent) -> None:
    _agent_json_path(agent.agent_id).write_text(
        json.dumps(asdict(agent), indent=2), encoding="utf-8"
    )


def _bouzecode_launch_cmd() -> list[str]:
    """Launch bouzecode via `python -m bouzecode` — avoids Windows .exe shim file locks."""
    return [sys.executable, "-m", "bouzecode"]


def create_agent(prompt: str, model: str, cwd: str) -> Agent:
    agent_id = uuid.uuid4().hex[:12]
    stdout_path = AGENTS_DIR / f"{agent_id}.out.log"
    session_path = AGENTS_DIR / f"{agent_id}.session.json"
    ipc_dir = AGENTS_DIR / f"{agent_id}.ipc"
    ipc_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        *_bouzecode_launch_cmd(), "-p", "--accept-all",
        "--session-file", str(session_path),
        "--web-agent-dir", str(ipc_dir),
    ]
    if model:
        cmd += ["-m", model]
    cmd.append(prompt)

    stdout_file = stdout_path.open("wb")
    process = subprocess.Popen(
        cmd,
        cwd=cwd or None,
        stdout=stdout_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
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


def list_agents() -> list[Agent]:
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
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
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
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
    )

    agent.pid = process.pid
    agent.model = use_model
    agent.finished_at = ""
    agent.returncode = None
    _save(agent)
    return agent


def continue_agent(agent: Agent, prompt: str, model: str = "") -> Agent:
    """Respawn a finished agent as the same session (same ID, logs, IPC)."""
    return _respawn(
        agent,
        extra_args=[prompt],
        banner=f"\n\n--- Session continued ---\n\n\u00bb {prompt}\n\n",
        model=model,
    )


def resume_pending_agent(agent: Agent, answer: str, model: str = "") -> Agent:
    """Respawn a paused agent to consume `<session>.pending.json` with the answer."""
    return _respawn(
        agent,
        extra_args=["--resume-pending", answer],
        banner=f"\n\n--- Resuming from AskUserQuestion ---\n\u00bb {answer}\n\n",
        model=model,
    )


def get_ipc_state(agent: Agent) -> dict:
    if not agent.ipc_dir:
        return {"status": "unknown"}
    paths = ipc.from_dir(agent.ipc_dir)
    return ipc.read_state(paths)


def resume_interrupted_agents() -> list[Agent]:
    """Called at Flask startup. Mark dead agents whose returncode was never set
    as finished (rc=-1 if IPC didn't reach 'finished'). No auto-respawn: each
    turn is a fresh process, user explicitly triggers continue."""
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
        ipc_status = get_ipc_state(agent).get("status")
        agent.returncode = 0 if ipc_status in ("finished", "awaiting_input") else -1
        # Overwrite stale IPC so future page loads see the real status
        if agent.ipc_dir and ipc_status not in ("finished",):
            ipc.write_state(ipc.from_dir(agent.ipc_dir), ipc.STATUS_FINISHED)
        _save(agent)
    return []


def kill_agent(agent: Agent) -> None:
    if agent.ipc_dir:
        paths = ipc.from_dir(agent.ipc_dir)
        paths.cancel.write_text("", encoding="utf-8")
    if psutil.pid_exists(agent.pid):
        psutil.Process(agent.pid).terminate()
    refresh_agent_status(agent)
