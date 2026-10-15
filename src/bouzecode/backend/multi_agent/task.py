# [desc] Defines SubAgentTask dataclass and helpers for git worktree management and sub-agent execution. [/desc]
from __future__ import annotations

import os
import queue
import subprocess
import tempfile
import uuid
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class SubAgentTask:
    id: str
    prompt: str
    status: str = "pending"
    result: Optional[str] = None
    depth: int = 0
    name: str = ""
    worktree_path: str = ""
    worktree_branch: str = ""
    result_file: str = ""  # enfant en fenêtre de terminal : son --result-file (et son .pid)
    model: str = ""
    agent_type: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    _cancel_flag: bool = False
    _future: Optional[Future] = field(default=None, repr=False)
    _inbox: Any = field(default_factory=queue.Queue, repr=False)


def _git_root(cwd: str) -> Optional[str]:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
        )
        return r.stdout.strip()
    except Exception:
        return None


def _create_worktree(base_dir: str) -> tuple:
    branch = f"nano-agent-{uuid.uuid4().hex[:8]}"
    wt_path = tempfile.mkdtemp(prefix="nano-agent-wt-")
    os.rmdir(wt_path)
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, wt_path],
        cwd=base_dir, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return wt_path, branch


def _remove_worktree(wt_path: str, branch: str, base_dir: str) -> None:
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", wt_path],
            cwd=base_dir, capture_output=True,
        )
    except Exception:
        pass
    try:
        subprocess.run(
            ["git", "branch", "-D", branch],
            cwd=base_dir, capture_output=True,
        )
    except Exception:
        pass


def _agent_run(prompt, state, config, system_prompt, depth=0, cancel_check=None):
    """Un run de sous-agent en process. À sa fin, le minuteur de compaction avant
    expiration du cache tombe : un sous-agent fini n'attend aucun humain, et compacter
    sa note serait payer un juge et un résumé pour une conversation peut-être close."""
    from .. import agent as _agent_mod
    from ..context_manager.compact_precache import desarmer_minuteur
    try:
        return (yield from _agent_mod.run(prompt, state, config, system_prompt,
                                          depth=depth, cancel_check=cancel_check))
    finally:
        desarmer_minuteur(state)


def _extract_final_text(messages):
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            return msg["content"]
    return None
