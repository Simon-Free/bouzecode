# [desc] Unit tests for the plan-mode permission gate: which tools are allowed while the agent is in read-only plan mode. [/desc]
"""What plan mode allows and blocks — unit level on purpose.

The tool *results* of EnterPlanMode/ExitPlanMode (mode activated, "Already in
plan mode", empty plan rejected, "Not in plan mode", plan echoed on exit) are
covered by real conversations in test_plan_tools_e2e.py.

The permission gate is not: the e2e harness replaces `_check_permission` with an
always-true stub as soon as a mock LLM is wired, so no conversation can show a
Write being refused while in plan mode. That decision — reads allowed, writes
refused except to the plan file itself, plan tools always auto-approved — is what
this file pins, by asking the real `_check_permission` directly.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from bouzecode.backend.tools import _enter_plan_mode
from bouzecode.backend.agent import _check_permission


@pytest.fixture
def in_plan_mode():
    """A config really switched into plan mode by EnterPlanMode, in a temp cwd."""
    tmpdir = Path(tempfile.mkdtemp(prefix="plan_perm_"))
    orig_cwd = os.getcwd()
    os.chdir(str(tmpdir))
    config = {"permission_mode": "auto", "_session_id": "tooltest"}
    _enter_plan_mode({"task_description": "Add WebSocket support"}, config)
    try:
        yield config, tmpdir, Path(config["_plan_file"])
    finally:
        os.chdir(orig_cwd)
        shutil.rmtree(str(tmpdir), ignore_errors=True)


def test_entering_plan_mode_switches_the_permission_mode(in_plan_mode):
    """EnterPlanMode really puts the session in read-only 'plan' mode."""
    config, _tmpdir, plan_path = in_plan_mode
    assert config["permission_mode"] == "plan"
    assert plan_path.exists()


@pytest.mark.parametrize("tool", ["Read", "Glob", "Grep"])
def test_reads_stay_allowed_in_plan_mode(in_plan_mode, tool):
    """Exploring the codebase is exactly what plan mode is for."""
    config, _tmpdir, _plan = in_plan_mode
    assert _check_permission({"name": tool, "input": {}}, config) is True


@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_writes_to_other_files_are_blocked_in_plan_mode(in_plan_mode, tool):
    """Touching real source files before the plan is approved is refused."""
    config, tmpdir, _plan = in_plan_mode
    call = {"name": tool, "input": {"file_path": str(tmpdir / "x.py")}}
    assert _check_permission(call, config) is False


@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_writing_the_plan_file_itself_is_allowed(in_plan_mode, tool):
    """The one file the agent may write in plan mode is the plan."""
    config, _tmpdir, plan_path = in_plan_mode
    call = {"name": tool, "input": {"file_path": str(plan_path)}}
    assert _check_permission(call, config) is True


@pytest.mark.parametrize("mode", ["plan", "auto", "manual"])
@pytest.mark.parametrize("tool", ["EnterPlanMode", "ExitPlanMode"])
def test_plan_tools_are_never_gated(in_plan_mode, mode, tool):
    """Entering and leaving plan mode never asks the user for permission,
    whatever the current permission mode."""
    config, _tmpdir, _plan = in_plan_mode
    config["permission_mode"] = mode
    assert _check_permission({"name": tool, "input": {}}, config) is True


def test_system_prompt_tells_the_model_how_to_plan(in_plan_mode):
    """Static-config invariant: the plan flow stays discoverable in the system
    prompt (a conversation hard-codes the call, so it cannot prove this)."""
    from bouzecode.backend.core.context import build_system_prompt

    config, _tmpdir, _plan = in_plan_mode
    config["permission_mode"] = "auto"
    assert "WritePlan" in build_system_prompt(config)
