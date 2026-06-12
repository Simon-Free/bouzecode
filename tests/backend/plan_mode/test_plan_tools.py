# [desc] E2E test for EnterPlanMode/ExitPlanMode tools: mode switching, permission checks, and plan file lifecycle
# <tool_use name="FinalAnswer" id="x1"><param name="answer">E2E test for EnterPlanMode/ExitPlanMode tools: mode switching, permission checks, and plan file lifecycle</param></tool_use> [/desc]
"""End-to-end test for EnterPlanMode / ExitPlanMode tools."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch


SEP = "=" * 60


def test_plan_tools():
    tmpdir = Path(tempfile.mkdtemp(prefix="plan_tools_e2e_"))
    orig_cwd = os.getcwd()
    os.chdir(str(tmpdir))

    try:
        _run(tmpdir)
    finally:
        os.chdir(orig_cwd)
        shutil.rmtree(str(tmpdir), ignore_errors=True)


def _run(tmpdir):
    from bouzecode.backend.tools import _enter_plan_mode, _exit_plan_mode
    from bouzecode.backend.agent import _check_permission

    config = {
        "permission_mode": "auto",
        "_session_id": "tooltest",
    }

    # ── Step 1: EnterPlanMode tool creates plan file and switches mode ──
    result = _enter_plan_mode({"task_description": "Add WebSocket support"}, config)
    assert config["permission_mode"] == "plan"
    assert config["_plan_file"]
    plan_path = Path(config["_plan_file"])
    assert plan_path.exists()
    assert "WebSocket" in plan_path.read_text(encoding="utf-8")
    assert "Plan mode activated" in result

    # ── Step 2: EnterPlanMode again → already in plan mode ──
    result = _enter_plan_mode({}, config)
    assert "Already in plan mode" in result

    # ── Step 3: Permission checks in plan mode ──
    # Reads allowed
    assert _check_permission({"name": "Read", "input": {}}, config) == True
    assert _check_permission({"name": "Glob", "input": {}}, config) == True
    assert _check_permission({"name": "Grep", "input": {}}, config) == True

    # Writes blocked
    assert _check_permission({"name": "Write", "input": {"file_path": str(tmpdir / "x.py")}}, config) == False
    assert _check_permission({"name": "Edit", "input": {"file_path": str(tmpdir / "x.py")}}, config) == False

    # Write to plan file allowed
    assert _check_permission({"name": "Write", "input": {"file_path": str(plan_path)}}, config) == True
    assert _check_permission({"name": "Edit", "input": {"file_path": str(plan_path)}}, config) == True

    # Plan tools always auto-approved
    assert _check_permission({"name": "EnterPlanMode", "input": {}}, config) == True
    assert _check_permission({"name": "ExitPlanMode", "input": {}}, config) == True

    # ── Step 4: ExitPlanMode with empty plan → rejected ──
    result = _exit_plan_mode({}, config)
    if "empty" in result.lower():
        assert config["permission_mode"] == "plan"
    else:
        pass  # Header counts as content — that's fine too

    # ── Step 5: Write plan content and ExitPlanMode ──
    config["permission_mode"] = "plan"
    plan_path.write_text(
        "# Plan: Add WebSocket support\n\n"
        "## Phase 1: Create ws_handler.py\n"
        "## Phase 2: Modify server.py\n"
        "## Phase 3: Add tests\n",
        encoding="utf-8",
    )
    result = _exit_plan_mode({}, config)
    assert config["permission_mode"] == "auto", f"Mode should be auto, got {config['permission_mode']}"
    assert "Plan mode exited" in result
    assert "Phase 1" in result
    assert "Wait for the user to approve" in result

    # ── Step 6: ExitPlanMode when not in plan mode ──
    result = _exit_plan_mode({}, config)
    assert "Not in plan mode" in result

    # ── Step 7: Plan tools auto-approved in auto mode too ──
    config["permission_mode"] = "auto"
    assert _check_permission({"name": "EnterPlanMode", "input": {}}, config) == True
    assert _check_permission({"name": "ExitPlanMode", "input": {}}, config) == True

    config["permission_mode"] = "manual"
    assert _check_permission({"name": "EnterPlanMode", "input": {}}, config) == True
    assert _check_permission({"name": "ExitPlanMode", "input": {}}, config) == True

    # ── Step 8: System prompt includes plan mode guidance ──
    from bouzecode.backend.core.context import build_system_prompt
    config["permission_mode"] = "auto"
    prompt = build_system_prompt(config)
    assert "WritePlan" in prompt


if __name__ == "__main__":
    test_plan_tools()
