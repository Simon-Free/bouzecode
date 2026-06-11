# [desc] Manages spawning, lifecycle, and isolation of concurrent sub-agent tasks with worktree support. [/desc]
from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from ..multi_agent.definitions import AgentDefinition
from ..multi_agent.task import (
    SubAgentTask,
    _git_root,
    _create_worktree,
    _remove_worktree,
    _extract_final_text,
)
from ..multi_agent import task as _task_mod


class SubAgentManager:

    def __init__(self, max_concurrent: int = 5, max_depth: int = 5):
        self.tasks: Dict[str, SubAgentTask] = {}
        self._by_name: Dict[str, str] = {}
        self.max_concurrent = max_concurrent
        self.max_depth = max_depth
        self._pool = ThreadPoolExecutor(max_workers=max_concurrent)

    # Profile hook name -> loop config flag it toggles.
    _HOOK_FLAGS = {
        "test_enforcement": "enforce_tests",
        "enforcement":      "enforce_methodology",
        "loop_detection":   "detect_loops",
    }

    def _apply_profile(self, profile, config: dict, base_prompt: str) -> str:
        """Apply a resolved AgentProfile onto a sub-agent's effective config:
        toggle loop-behavior flags from `hooks` (a "no-" prefix disables), carry
        model/tools/skills, and append the profile's system_prompt_extra."""
        for hook in (profile.hooks or []):
            enabled = not hook.startswith("no-")
            key = hook[3:] if hook.startswith("no-") else hook
            flag = self._HOOK_FLAGS.get(key)
            if flag is not None:
                config[flag] = enabled
        if getattr(profile, "model", ""):
            config["model"] = profile.model
        if getattr(profile, "tools", None):
            config["_allowed_tools"] = list(profile.tools)
        if getattr(profile, "skills", None):
            config["_profile_skills"] = list(profile.skills)
        extra = getattr(profile, "system_prompt_extra", "") or ""
        return f"{base_prompt}\n\n{extra}".rstrip() if extra else base_prompt

    def _resolve_profiles(self, names: list):
        """Load profiles named *names* from the cwd .bouzecode/ and any registered
        extra dirs, merge them in order, and return the merged AgentProfile (or
        None if none of the names matched)."""
        from pathlib import Path
        from ..profiles import load_profiles_from_dir, merge_profiles
        from ..core.paths import get_extra_dirs

        roots = [Path.cwd() / ".bouzecode", *get_extra_dirs()]
        available: dict = {}
        for root in roots:
            pdir = root / "profiles"
            if pdir.is_dir():
                available.update(load_profiles_from_dir(pdir))
        matched = [available[n] for n in names if n in available]
        if not matched:
            return None
        return merge_profiles(matched)

    def create_task(self, prompt: str, depth: int = 0, name: str = "") -> SubAgentTask:
        """Create and register a task without spawning a thread.

        Used by the terminal-spawn path which manages its own subprocess.
        """
        task_id = uuid.uuid4().hex[:12]
        short_name = name or task_id[:8]
        task = SubAgentTask(id=task_id, prompt=prompt, depth=depth, name=short_name)
        self.tasks[task_id] = task
        if name:
            self._by_name[name] = task_id
        return task

    def spawn(
        self,
        prompt: str,
        config: dict,
        system_prompt: str,
        depth: int = 0,
        agent_def: Optional[AgentDefinition] = None,
        isolation: str = "",
        name: str = "",
    ) -> SubAgentTask:
        task_id = uuid.uuid4().hex[:12]
        short_name = name or task_id[:8]
        task = SubAgentTask(id=task_id, prompt=prompt, depth=depth, name=short_name)
        self.tasks[task_id] = task
        if name:
            self._by_name[name] = task_id

        if depth >= self.max_depth:
            task.status = "failed"
            task.result = f"Max depth ({self.max_depth}) exceeded"
            return task

        eff_config = dict(config)
        eff_system = system_prompt

        if agent_def:
            if agent_def.model:
                eff_config["model"] = agent_def.model
            if agent_def.system_prompt:
                eff_system = agent_def.system_prompt.rstrip() + "\n\n" + system_prompt
            task.agent_type = agent_def.name
        task.model = eff_config.get("model", "")

        worktree_path = ""
        worktree_branch = ""
        base_dir = os.getcwd()

        if isolation == "worktree":
            git_root = _git_root(base_dir)
            if not git_root:
                task.status = "failed"
                task.result = "isolation='worktree' requires a git repository"
                return task
            try:
                worktree_path, worktree_branch = _create_worktree(git_root)
                task.worktree_path = worktree_path
                task.worktree_branch = worktree_branch
                notice = (
                    f"\n\n[Note: You are working in an isolated git worktree at "
                    f"{worktree_path} (branch: {worktree_branch}). "
                    f"Your changes are isolated from the main workspace at {git_root}. "
                    f"Commit your changes before finishing so they can be reviewed/merged.]"
                )
                prompt = prompt + notice
            except Exception as e:
                task.status = "failed"
                task.result = f"Failed to create worktree: {e}"
                return task

        def _run():
            from .. import agent as _agent_mod; AgentState = _agent_mod.AgentState
            task.status = "running"
            old_cwd = os.getcwd()
            try:
                if worktree_path:
                    os.chdir(worktree_path)

                state = AgentState()
                gen = _task_mod._agent_run(
                    prompt, state, eff_config, eff_system,
                    depth=depth + 1,
                    cancel_check=lambda: task._cancel_flag,
                )
                for _event in gen:
                    if task._cancel_flag:
                        break

                if task._cancel_flag:
                    task.status = "cancelled"
                    task.result = None
                else:
                    task.result = _extract_final_text(state.messages)
                    task.status = "completed"

                while not task._inbox.empty() and not task._cancel_flag:
                    inbox_msg = task._inbox.get_nowait()
                    task.status = "running"
                    gen2 = _task_mod._agent_run(
                        inbox_msg, state, eff_config, eff_system,
                        depth=depth + 1,
                        cancel_check=lambda: task._cancel_flag,
                    )
                    for _ev in gen2:
                        if task._cancel_flag:
                            break
                    if not task._cancel_flag:
                        task.result = _extract_final_text(state.messages)
                        task.status = "completed"

                task.input_tokens = state.total_input_tokens
                task.output_tokens = state.total_output_tokens
                task.cache_read_tokens = state.total_cache_read_tokens
                task.cache_creation_tokens = state.total_cache_creation_tokens

            except Exception as e:
                task.status = "failed"
                task.result = f"Error: {e}"
            finally:
                if worktree_path:
                    os.chdir(old_cwd)
                    _remove_worktree(worktree_path, worktree_branch, old_cwd)

        task._future = self._pool.submit(_run)
        return task

    def wait(self, task_id: str, timeout: float = None) -> Optional[SubAgentTask]:
        task = self.tasks.get(task_id)
        if task is None:
            return None
        if task._future is not None:
            try:
                task._future.result(timeout=timeout)
            except Exception:
                pass
        return task

    def get_result(self, task_id: str) -> Optional[str]:
        task = self.tasks.get(task_id)
        return task.result if task else None

    def list_tasks(self) -> List[SubAgentTask]:
        return list(self.tasks.values())

    def send_message(self, task_id_or_name: str, message: str) -> bool:
        task_id = self._by_name.get(task_id_or_name, task_id_or_name)
        task = self.tasks.get(task_id)
        if task is None:
            return False
        if task.status not in ("running", "pending"):
            return False
        task._inbox.put(message)
        return True

    def cancel(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        if task is None:
            return False
        if task.status == "running":
            task._cancel_flag = True
            return True
        return False

    def shutdown(self) -> None:
        for task in self.tasks.values():
            if task.status == "running":
                task._cancel_flag = True
        self._pool.shutdown(wait=True)
