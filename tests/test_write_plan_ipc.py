# [desc] Tests that _write_plan saves plan.md to IPC directory and handles edge cases correctly. [/desc]
"""Tests for _write_plan saving plan.md into IPC dir."""
from __future__ import annotations

from pathlib import Path

import pytest


class TestWritePlanIpc:
    """Test that _write_plan saves plan.md into IPC dir when configured."""

    def test_write_plan_creates_ipc_plan(self, tmp_path):
        ipc_dir = tmp_path / "ipc"
        ipc_dir.mkdir()
        config = {
            "_session_id": "test_sess",
            "_web_agent_dir": str(ipc_dir),
        }
        plans_dir = Path.cwd() / ".nano_claude" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        from tools.plan_mode import _write_plan
        result = _write_plan({"content": "# Test Plan\n\nStep 1"}, config)
        assert "Plan saved" in result
        ipc_plan = ipc_dir / "plan.md"
        assert ipc_plan.exists()
        assert "Test Plan" in ipc_plan.read_text(encoding="utf-8")

    def test_write_plan_without_ipc_dir(self, tmp_path):
        config = {"_session_id": "test_no_ipc"}
        plans_dir = Path.cwd() / ".nano_claude" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        from tools.plan_mode import _write_plan
        result = _write_plan({"content": "# Plan\n\nContent"}, config)
        assert "Plan saved" in result

    def test_write_plan_sets_plan_file_in_config(self, tmp_path):
        config = {"_session_id": "test_config"}
        plans_dir = Path.cwd() / ".nano_claude" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        from tools.plan_mode import _write_plan
        _write_plan({"content": "# Plan"}, config)
        assert "_plan_file" in config
        assert config["_plan_file"].endswith(".md")

    def test_write_plan_empty_content_rejected(self):
        from tools.plan_mode import _write_plan
        result = _write_plan({"content": "   "}, {})
        assert "empty" in result.lower()

    def test_multiple_plans_accumulated_in_ipc(self, tmp_path):
        ipc_dir = tmp_path / "ipc"
        ipc_dir.mkdir()
        config = {"_session_id": "test_multi", "_web_agent_dir": str(ipc_dir)}
        from tools.plan_mode import _write_plan
        _write_plan({"content": "# Plan 1\nFirst"}, config)
        _write_plan({"content": "# Plan 2\nSecond"}, config)
        ipc_plan = ipc_dir / "plan.md"
        text = ipc_plan.read_text(encoding="utf-8")
        assert "Plan 1" in text
        assert "Plan 2" in text
        assert "---" in text

    def test_multiple_plans_accumulated_in_config(self, tmp_path):
        config = {"_session_id": "test_multi_cfg"}
        from tools.plan_mode import _write_plan
        _write_plan({"content": "# Plan A"}, config)
        _write_plan({"content": "# Plan B"}, config)
        assert len(config["_all_plans"]) == 2
        assert config["_all_plans"][0] == "# Plan A"
        assert config["_all_plans"][1] == "# Plan B"


class TestExtractPlanContent:
    """Test that extract_plan_content returns all plans from session JSON."""

    def test_single_plan_extracted(self, tmp_path):
        session = {"messages": [
            {"role": "assistant", "tool_calls": [
                {"name": "WritePlan", "input": {"content": "# Plan 1"}}
            ]}
        ]}
        p = tmp_path / "session.json"
        import json
        p.write_text(json.dumps(session), encoding="utf-8")
        from web.session_service import extract_plan_content
        result = extract_plan_content(str(p))
        assert result == "# Plan 1"

    def test_multiple_plans_joined(self, tmp_path):
        session = {"messages": [
            {"role": "assistant", "tool_calls": [
                {"name": "WritePlan", "input": {"content": "# Plan 1\nFirst"}}
            ]},
            {"role": "user", "content": "ok"},
            {"role": "assistant", "tool_calls": [
                {"name": "WritePlan", "input": {"content": "# Plan 2\nSecond"}}
            ]},
        ]}
        p = tmp_path / "session.json"
        import json
        p.write_text(json.dumps(session), encoding="utf-8")
        from web.session_service import extract_plan_content
        result = extract_plan_content(str(p))
        assert "Plan 1" in result
        assert "Plan 2" in result
        assert "---" in result

    def test_empty_plan_skipped(self, tmp_path):
        session = {"messages": [
            {"role": "assistant", "tool_calls": [
                {"name": "WritePlan", "input": {"content": "  "}},
                {"name": "WritePlan", "input": {"content": "# Real Plan"}}
            ]}
        ]}
        p = tmp_path / "session.json"
        import json
        p.write_text(json.dumps(session), encoding="utf-8")
        from web.session_service import extract_plan_content
        result = extract_plan_content(str(p))
        assert result == "# Real Plan"
