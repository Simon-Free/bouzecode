# [desc] E2E tests verifying Kanban/Todo tab styling consistency and active state across pages [/desc]
"""E2E tests: Kanban/Todo tabs must have identical styling on both pages."""
import json
import tempfile
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import sync_playwright


@pytest.fixture(scope="module")
def live_server():
    """Start the Flask app on a free port with a test project available."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ..web.app import create_app
    from ..web.projects import PROJECTS_FILE, add_project

    # Create a temporary directory to act as a fake project
    tmp_dir = tempfile.mkdtemp(prefix="e2e_test_project_")

    # Add a test project
    add_project("e2e-test", tmp_dir)

    app = create_app()
    app.config["TESTING"] = True
    port = 5199
    server = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False),
        daemon=True,
    )
    server.start()
    time.sleep(1.5)
    yield f"http://127.0.0.1:{port}"

    # Cleanup: remove test project from JSON
    if PROJECTS_FILE.exists():
        projects = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
        projects = [p for p in projects if p["name"] != "e2e-test"]
        PROJECTS_FILE.write_text(json.dumps(projects), encoding="utf-8")


def _get_tab_styles(page, url):
    """Navigate to url and return dict {active: style_dict, inactive: style_dict}."""
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector(".project-tabs a", timeout=5000)
    tabs = page.query_selector_all(".project-tabs a")
    result = {"active": None, "inactive": None}
    for tab in tabs:
        style = tab.evaluate("""el => {
            const cs = window.getComputedStyle(el);
            return {
                fontSize: cs.fontSize,
                fontWeight: cs.fontWeight,
                color: cs.color,
                padding: cs.padding,
                borderBottom: cs.borderBottomWidth + ' ' + cs.borderBottomStyle + ' ' + cs.borderBottomColor,
                textDecoration: cs.textDecorationLine,
                isActive: el.classList.contains('active'),
            };
        }""")
        if style.pop("isActive"):
            result["active"] = style
        else:
            result["inactive"] = style
    return result


def test_tabs_have_consistent_styles_between_kanban_and_todo(live_server):
    """Active tabs must look the same on both pages; inactive tabs must look the same on both pages."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="msedge")
        page = browser.new_page()

        kanban_url = f"{live_server}/kanban/e2e-test"
        todo_url = f"{live_server}/todo/e2e-test"

        kanban_styles = _get_tab_styles(page, kanban_url)
        todo_styles = _get_tab_styles(page, todo_url)

        browser.close()

    assert kanban_styles["active"] is not None, "No active tab found on kanban page"
    assert todo_styles["active"] is not None, "No active tab found on todo page"
    assert kanban_styles["inactive"] is not None, "No inactive tab found on kanban page"
    assert todo_styles["inactive"] is not None, "No inactive tab found on todo page"

    # Active tabs must have same style regardless of which page we're on
    ks, ts = kanban_styles["active"], todo_styles["active"]
    for prop in ("fontSize", "fontWeight", "color", "padding", "borderBottom"):
        assert ks[prop] == ts[prop], (
            f"Active tab {prop} differs: kanban={ks[prop]}, todo={ts[prop]}"
        )

    # Inactive tabs must have same style regardless of which page we're on
    ks, ts = kanban_styles["inactive"], todo_styles["inactive"]
    for prop in ("fontSize", "fontWeight", "color", "padding", "borderBottom"):
        assert ks[prop] == ts[prop], (
            f"Inactive tab {prop} differs: kanban={ks[prop]}, todo={ts[prop]}"
        )


def test_active_tab_matches_current_page(live_server):
    """The active tab should correspond to the current page."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="msedge")
        page = browser.new_page()

        # On kanban page, first tab (Kanban) should be active
        page.goto(f"{live_server}/kanban/e2e-test", wait_until="domcontentloaded")
        page.wait_for_selector(".project-tabs a", timeout=5000)
        tabs = page.query_selector_all(".project-tabs a")
        assert len(tabs) >= 2
        assert "active" in (tabs[0].get_attribute("class") or "")
        assert "active" not in (tabs[1].get_attribute("class") or "")

        # On todo page, second tab (Todo) should be active
        page.goto(f"{live_server}/todo/e2e-test", wait_until="domcontentloaded")
        page.wait_for_selector(".project-tabs a", timeout=5000)
        tabs = page.query_selector_all(".project-tabs a")
        assert len(tabs) >= 2
        assert "active" not in (tabs[0].get_attribute("class") or "")
        assert "active" in (tabs[1].get_attribute("class") or "")

        browser.close()
