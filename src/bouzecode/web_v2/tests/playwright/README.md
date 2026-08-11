# web_v2/tests/playwright/

## Purpose

Browser tests for the web UI, run against the real Flask application served by a real
werkzeug server and driven by a real Chromium.

A test belongs here only when the behaviour is invisible to the Flask test client:
computed CSS, pixel geometry, actual JavaScript execution, a user's click or scroll.
Anything that reduces to "this route answers that" or "this element is in the rendered
HTML" is tested with `client.get(...)` in the parent folder and runs far faster.

The whole folder skips cleanly when `playwright` or Chromium is absent.

## Usage

- `conftest.py` — `server` (the real app on a free local port), `browser`
  (session-scoped Chromium, skipped if unavailable), `page` (a fresh 1280x800 page per
  test), `page_with_console_errors` (a page plus its live list of console and pageerror
  messages), and `VIEWPORT`.
- `test_pages_boot_smoke.py` — single smoke pass: every page of the app loads with no
  JavaScript error.
- `test_conversations_layout_b5_e2e.py` — the `/conversations` layout measured in real
  pixels: composer, tabs, cards.
- `test_conversations_switch_id_e2e.py` — the Conversation/Recap switch sits on the meta
  line and the short id appears exactly once.
- `test_agents_catalog_e2e.py` — installing an agent from the catalog moves it into the
  installed list without a page reload.
- `test_recap_diff_scroll.py` — the recap diff panes are genuinely scrollable, per the
  CSS the browser computes.
