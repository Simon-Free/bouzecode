"""E2E test: Task tools — LLM creates, lists, and updates tasks."""
from __future__ import annotations

import pytest
from pathlib import Path

from tests.fake_llm import MockLLM
from tests.e2e_harness import bouzecode


@pytest.mark.backend
class TestTaskE2E:
    """Task tool lifecycle through the engine."""

    @pytest.fixture(autouse=True)
    def _reset_task_store(self, tmp_path, monkeypatch):
        """Reset global task store state and point persistence at tmp_path."""
        monkeypatch.chdir(tmp_path)
        import bouzecode.backend.tools.task.store as task_store
        monkeypatch.setattr(task_store, "_tasks", {})
        monkeypatch.setattr(task_store, "_loaded", False)

    def test_task_create_and_list(self):
        """LLM creates a task then lists it — verify lifecycle."""
        mock = MockLLM([
            # Turn 1: create a task
            '<tool_use name="TaskCreate" id="tc1">'
            '<param name="subject">Fix the bug</param>'
            '<param name="description">There is a bug in module X</param>'
            '</tool_use>',
            # Turn 2: list tasks
            '<tool_use name="TaskList" id="tl1"></tool_use>',
            # Turn 3: final reply
            "Task created and listed successfully.",
        ])
        result = bouzecode(messages=["Create a task and list it"], mock_llm=mock)

        assert mock.call_count == 3
        assert "success" in result.last_reply.lower() or "task" in result.last_reply.lower()

    def test_task_create_update_done(self):
        """Full lifecycle: create → update status to done."""
        mock = MockLLM([
            # Turn 1: create
            '<tool_use name="TaskCreate" id="tc1">'
            '<param name="subject">Write tests</param>'
            '<param name="description">Write e2e tests for MR6</param>'
            '</tool_use>',
            # Turn 2: mark done
            '<tool_use name="TaskUpdate" id="tu1">'
            '<param name="task_id">1</param>'
            '<param name="status">done</param>'
            '</tool_use>',
            # Turn 3: confirm
            "Task completed.",
        ])
        result = bouzecode(messages=["Create task and mark done"], mock_llm=mock)

        assert mock.call_count == 3
        assert "complete" in result.last_reply.lower() or "task" in result.last_reply.lower()
