# [desc] Tests for per-project TODO notepad service persistence and Flask API routes (CRUD, isolation) [/desc]
"""Tests for the per-project TODO notepad feature."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ...web import todo as todo_module


@pytest.fixture
def todo_dir(tmp_path):
    d = tmp_path / "kanban"
    with patch.object(todo_module, "KANBAN_DIR", d):
        yield d


class TestTodoService:
    def test_load_empty_when_no_file(self, todo_dir):
        assert todo_module.load("proj1") == ""

    def test_save_and_load(self, todo_dir):
        todo_module.save("proj1", "hello world")
        assert todo_module.load("proj1") == "hello world"

    def test_unicode(self, todo_dir):
        todo_module.save("proj1", "日本語テスト 🎉")
        assert todo_module.load("proj1") == "日本語テスト 🎉"

    def test_projects_isolated(self, todo_dir):
        todo_module.save("proj1", "aaa")
        todo_module.save("proj2", "bbb")
        assert todo_module.load("proj1") == "aaa"
        assert todo_module.load("proj2") == "bbb"

    def test_overwrite(self, todo_dir):
        todo_module.save("proj1", "first")
        todo_module.save("proj1", "second")
        assert todo_module.load("proj1") == "second"


@pytest.fixture
def client(tmp_path):
    kanban_dir = tmp_path / "kanban"
    projects_file = tmp_path / "projects.json"
    from ..web import kanban as kanban_mod, projects as proj_mod
    with patch.object(kanban_mod, "KANBAN_DIR", kanban_dir), \
         patch.object(proj_mod, "PROJECTS_FILE", projects_file), \
         patch.object(todo_module, "KANBAN_DIR", kanban_dir):
        proj_mod.add_project("testproj", "C:\\fake")
        from ..web.app import create_app
        app = create_app()
        app.config["TESTING"] = True
        yield app.test_client()


class TestTodoAPI:
    def test_page_renders(self, client):
        rv = client.get("/todo/testproj")
        assert rv.status_code == 200
        assert b"todo-editor" in rv.data

    def test_page_404_unknown_project(self, client):
        rv = client.get("/todo/unknown")
        assert rv.status_code == 404

    def test_api_put_and_get(self, client):
        rv = client.put("/api/todo/testproj",
                        data=json.dumps({"content": "my notes"}),
                        content_type="application/json")
        assert rv.status_code == 200
        rv = client.get("/api/todo/testproj")
        data = json.loads(rv.data)
        assert data["content"] == "my notes"

    def test_api_get_empty(self, client):
        rv = client.get("/api/todo/testproj")
        data = json.loads(rv.data)
        assert data["content"] == ""
