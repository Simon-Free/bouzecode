# [desc] Playwright-based end-to-end tests for the BouzequI web interface using a live Flask server. [/desc]
"""Playwright tests for BouzequI web interface.

Uses a real Flask server + headless Chromium browser — no mocking.
"""
from __future__ import annotations

import json
import tempfile
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pytest
from playwright.sync_api import Page
from werkzeug.serving import make_server

import web.runner as runner_mod
from web.app import create_app
from web.runner import Agent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def live_server():
    """Start Flask on a random port for the entire test module."""
    _base = Path(tempfile.mkdtemp())
    old = runner_mod.AGENTS_DIR
    runner_mod.AGENTS_DIR = _base
    app = create_app()
    runner_mod.AGENTS_DIR = old
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def agents_dir(tmp_path):
    """Give each test its own empty agents directory."""
    old = runner_mod.AGENTS_DIR
    runner_mod.AGENTS_DIR = tmp_path
    yield tmp_path
    runner_mod.AGENTS_DIR = old


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(tmpdir: Path, agent_id: str, pid: int, returncode=None,
                finished_at="", ipc_status=None) -> Agent:
    """Create a real agent JSON + optional IPC state file in tmpdir."""
    ipc_dir = tmpdir / f"{agent_id}.ipc"
    ipc_dir.mkdir(parents=True, exist_ok=True)
    agent = Agent(
        agent_id=agent_id,
        prompt=f"task for {agent_id}",
        model="test-model",
        cwd=str(tmpdir),
        pid=pid,
        started_at=datetime.utcnow().isoformat() + "Z",
        finished_at=finished_at,
        returncode=returncode,
        stdout_path=str(tmpdir / f"{agent_id}.out.log"),
        session_path=str(tmpdir / f"{agent_id}.session.json"),
        ipc_dir=str(ipc_dir),
    )
    (tmpdir / f"{agent_id}.json").write_text(
        json.dumps(asdict(agent), indent=2), encoding="utf-8",
    )
    Path(agent.session_path).write_text(
        json.dumps({"messages": []}), encoding="utf-8",
    )
    Path(agent.stdout_path).write_text("", encoding="utf-8")
    if ipc_status:
        state = {"status": ipc_status, "updated_at": 0}
        if ipc_status == "awaiting_input":
            state["question"] = "Pick a color?"
            state["options"] = [{"label": "red"}, {"label": "blue"}]
        (ipc_dir / "state.json").write_text(
            json.dumps(state), encoding="utf-8",
        )
    return agent


# ---------------------------------------------------------------------------
# Tests: Navigation
# ---------------------------------------------------------------------------

class TestNavigation:
    def test_home_redirects_to_agents(self, page: Page, live_server):
        page.goto(f"{live_server}/")
        assert "/agents" in page.url


# ---------------------------------------------------------------------------
# Tests: Agent categorization on list page
# ---------------------------------------------------------------------------

class TestAgentCategorization:
    def test_awaiting_input_agents_separated(self, page: Page, live_server, agents_dir):
        _make_agent(agents_dir, "finished01", pid=99999, returncode=0,
                    finished_at="2026-01-01T00:00:00Z")
        _make_agent(agents_dir, "running01", pid=99998, returncode=0,
                    finished_at="2026-01-01T00:00:00Z", ipc_status="running")
        page.goto(f"{live_server}/agents")
        html = page.content()
        assert "finished01" in html
        assert "running01" in html
        assert "Termin" in html

    def test_finished_agents_in_finished_section(self, page: Page, live_server, agents_dir):
        _make_agent(agents_dir, "done01", pid=99997, returncode=0,
                    finished_at="2026-01-01T00:00:00Z")
        page.goto(f"{live_server}/agents")
        html = page.content()
        assert "done01" in html
        assert "Termin" in html

    def test_idle_agents_in_awaiting_section(self, page: Page, live_server, agents_dir):
        _make_agent(agents_dir, "idle01", pid=99990, returncode=0,
                    finished_at="2026-01-01T00:00:00Z", ipc_status="idle")
        _make_agent(agents_dir, "await01", pid=99989, returncode=0,
                    finished_at="2026-01-01T00:00:00Z", ipc_status="awaiting_input")
        page.goto(f"{live_server}/agents")
        html = page.content()
        assert "idle01" in html
        assert "await01" in html

    def test_empty_agents_shows_message(self, page: Page, live_server, agents_dir):
        page.goto(f"{live_server}/agents")
        html = page.content()
        assert "Aucun agent" in html


# ---------------------------------------------------------------------------
# Tests: List page polling JS
# ---------------------------------------------------------------------------

class TestListPageLiveUpdates:
    def test_finished_agents_not_tracked_in_initial_state(self, page: Page, live_server, agents_dir):
        _make_agent(agents_dir, "done01", pid=99980, returncode=0,
                    finished_at="2026-01-01T00:00:00Z")
        page.goto(f"{live_server}/agents")
        html = page.content()
        js_block = html.split("var initial")[1].split("var source")[0] if "var initial" in html else ""
        assert "done01" not in js_block

    def test_live_update_stream_wired(self, page: Page, live_server, agents_dir):
        page.goto(f"{live_server}/agents")
        html = page.content()
        assert "new EventSource('/agents/stream')" in html


# ---------------------------------------------------------------------------
# Tests: Agent state endpoint (JSON API via Playwright request)
# ---------------------------------------------------------------------------

class TestAgentState:
    def test_state_returns_awaiting_input(self, page: Page, live_server, agents_dir):
        _make_agent(agents_dir, "wait01", pid=99996, returncode=0,
                    finished_at="2026-01-01T00:00:00Z", ipc_status="awaiting_input")
        resp = page.request.get(f"{live_server}/agents/wait01/state")
        data = resp.json()
        assert data["ipc_status"] == "awaiting_input"
        assert data["question"] == "Pick a color?"
        assert len(data["options"]) == 2

    def test_state_returns_question_fields(self, page: Page, live_server, agents_dir):
        _make_agent(agents_dir, "q01", pid=99995, returncode=0,
                    finished_at="2026-01-01T00:00:00Z", ipc_status="idle")
        resp = page.request.get(f"{live_server}/agents/q01/state")
        data = resp.json()
        assert data["ipc_status"] == "idle"
        assert data["question"] is None

    def test_state_returns_running_flag(self, page: Page, live_server, agents_dir):
        _make_agent(agents_dir, "fin01", pid=99991, returncode=0,
                    finished_at="2026-01-01T00:00:00Z", ipc_status="finished")
        resp = page.request.get(f"{live_server}/agents/fin01/state")
        data = resp.json()
        assert data["running"] is False
        assert data["ipc_status"] == "finished"
        assert data["returncode"] == 0

    def test_state_includes_session_mtime(self, page: Page, live_server, agents_dir):
        _make_agent(agents_dir, "mt01", pid=99988, returncode=0,
                    finished_at="2026-01-01T00:00:00Z", ipc_status="idle")
        resp = page.request.get(f"{live_server}/agents/mt01/state")
        data = resp.json()
        assert "session_mtime" in data
        assert isinstance(data["session_mtime"], float)

    def test_state_not_found(self, page: Page, live_server, agents_dir):
        resp = page.request.get(f"{live_server}/agents/nonexistent999/state")
        assert resp.status == 404


# ---------------------------------------------------------------------------
# Tests: Plan IPC fallback (rendered via real browser)
# ---------------------------------------------------------------------------

class TestPlanIpcFallback:
    def test_plan_from_ipc_dir(self, page: Page, live_server, agents_dir):
        agent = _make_agent(agents_dir, "plan01", pid=99994, returncode=0,
                            finished_at="2026-01-01T00:00:00Z")
        ipc_plan = Path(agent.ipc_dir) / "plan.md"
        ipc_plan.write_text("# My Plan\n\n## Step 1\nDo things", encoding="utf-8")
        page.goto(f"{live_server}/agents/plan01/plan")
        html = page.content()
        assert "My Plan" in html
        assert "Step 1" in html

    def test_plan_from_session_json_takes_priority(self, page: Page, live_server, agents_dir):
        agent = _make_agent(agents_dir, "plan02", pid=99993, returncode=0,
                            finished_at="2026-01-01T00:00:00Z")
        session_data = {
            "messages": [{
                "role": "assistant",
                "content": "Here is my plan",
                "tool_calls": [{
                    "id": "tc1", "name": "WritePlan",
                    "input": {"content": "# Session Plan\n\nFrom session JSON"},
                }],
            }],
        }
        Path(agent.session_path).write_text(
            json.dumps(session_data), encoding="utf-8",
        )
        ipc_plan = Path(agent.ipc_dir) / "plan.md"
        ipc_plan.write_text("# IPC Plan\n\nShould be ignored", encoding="utf-8")
        page.goto(f"{live_server}/agents/plan02/plan")
        html = page.content()
        assert "Session Plan" in html
        assert "IPC Plan" not in html

    def test_no_plan_shows_empty_message(self, page: Page, live_server, agents_dir):
        _make_agent(agents_dir, "plan03", pid=99992, returncode=0,
                    finished_at="2026-01-01T00:00:00Z")
        page.goto(f"{live_server}/agents/plan03/plan")
        html = page.content()
        assert "Pas de plan" in html
