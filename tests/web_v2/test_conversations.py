# [desc] Tests for GET /conversations page: 200 + ChatGPT-like markup (sidebar, tabs, panels, conversations.js).
"""Verify the /conversations page renders with coherent .conv-* markup and the JS reference."""
from __future__ import annotations

import pytest


@pytest.fixture()
def client():
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestConversationsPage:
    def test_returns_200(self, client):
        resp = client.get("/conversations")
        assert resp.status_code == 200

    def test_layout_wrapper_present(self, client):
        html = client.get("/conversations").get_data(as_text=True)
        assert "conv-layout" in html

    def test_sidebar_present(self, client):
        html = client.get("/conversations").get_data(as_text=True)
        assert "conv-sidebar" in html
        assert 'id="conv-list"' in html

    def test_tabs_container_present(self, client):
        html = client.get("/conversations").get_data(as_text=True)
        assert 'id="conv-tabs"' in html

    def test_panels_container_present(self, client):
        html = client.get("/conversations").get_data(as_text=True)
        assert 'id="conv-panels"' in html

    def test_conversations_js_referenced(self, client):
        html = client.get("/conversations").get_data(as_text=True)
        assert "/static/js/conversations.js" in html
