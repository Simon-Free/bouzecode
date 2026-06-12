# [desc] Pytest conftest: loads .env, blocks real LLM calls, isolates global state between tests. [/desc]
"""Bouzecode OSS test configuration.

Loads .env at collection time. Autouse fixtures block accidental real LLM calls
and isolate global state between tests.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def _load_env_file(env_path: Path) -> None:
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_BOUZECODE_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _BOUZECODE_ROOT / ".env"

# Web tests (Playwright) are set aside by marker, but pytest still IMPORTS their
# modules at collection — without playwright installed every file errors out.
import importlib.util
if importlib.util.find_spec("playwright") is None:
    collect_ignore_glob = ["e2e/*", "e2e/**/*", "frontend/*", "frontend/**/*"]
if _ENV_FILE.exists():
    _load_env_file(_ENV_FILE)

if "ANTHROPIC_AUTH_TOKEN" in os.environ and "ANTHROPIC_API_KEY" not in os.environ:
    os.environ["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_AUTH_TOKEN"]

os.environ.setdefault("PYTHONHTTPSVERIFY", "0")


# RunPythonTest fixture-target files: excluded from the main suite.
# test_web_agents.py requires playwright (not installed in this env).
collect_ignore = [
    "backend/tools/runner/test_trivial_runner.py",
    "backend/tools/runner/test_trivial_runner_slow.py",
    "test_web_agents.py",
]


def pytest_configure(config):
    config.addinivalue_line("markers", "backend: agent-engine tests (tests/backend/)")
    config.addinivalue_line("markers", "ui: terminal-UI tests (tests/ui/)")
    config.addinivalue_line("markers", "web: Flask + Playwright web tests (tests/frontend/)")
    config.addinivalue_line("markers", "slow: fixture-target marker for the test-runner tests")


def pytest_collection_modifyitems(config, items):
    """Auto-mark every test by its top-level folder."""
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if "/tests/backend/" in path:
            item.add_marker("backend")
        elif "/tests/ui/" in path:
            item.add_marker("ui")
        elif "/tests/frontend/" in path:
            item.add_marker("web")


@pytest.fixture(autouse=True)
def _disable_web_ipc(monkeypatch):
    """Neutralize web-IPC mode so tests never raise PausedForInput."""
    monkeypatch.delenv("BOUZECODE_WEB_IPC_DIR", raising=False)


@pytest.fixture(autouse=True)
def _llm_network_guard(monkeypatch):
    """Hermetic guard: blocks real LLM calls unless explicitly opted in."""
    from tests import cache_conversation_helpers as cch
    cch.LIVE_API_ALLOWED = False
    try:
        import bouzecode.backend.agent.providers.backends.anthropic_stream as _a
        import bouzecode.backend.agent.providers.backends.dispatch as _d
    except Exception:
        return
    _real = _a.stream_anthropic

    def _gated(*args, **kwargs):
        if not getattr(cch, "LIVE_API_ALLOWED", False):
            raise RuntimeError(
                "Real LLM call blocked: this test reached the live socle without "
                "calling require_api_key(). Use MockLLM / e2e_harness for a "
                "deterministic fake, or call require_api_key() to opt in (it skips "
                "when credentials are absent)."
            )
        return _real(*args, **kwargs)

    monkeypatch.setattr(_a, "stream_anthropic", _gated, raising=False)
    monkeypatch.setattr(_d, "stream_anthropic", _gated, raising=False)


@pytest.fixture(autouse=True)
def _isolate_global_state():
    """Snapshot and restore process-global registries around each test."""
    _orig_cwd = os.getcwd()
    snapshots = []

    def _snap_collection(modpath, attr):
        try:
            mod = __import__(modpath, fromlist=[attr.lstrip("_")])
        except Exception:
            return
        live = getattr(mod, attr, None)
        if isinstance(live, dict):
            saved = dict(live)
            snapshots.append(lambda: (live.clear(), live.update(saved)))
        elif isinstance(live, set):
            saved = set(live)
            snapshots.append(lambda: (live.clear(), live.update(saved)))
        elif isinstance(live, list):
            saved = list(live)
            snapshots.append(lambda: live.__setitem__(slice(None), saved))

    _snap_collection("bouzecode.backend.core.tool_registry", "_registry")
    _snap_collection("bouzecode.backend.core.tool_registry", "_disabled")
    _snap_collection("bouzecode.backend.core.paths", "_extra_dirs")
    yield
    os.chdir(_orig_cwd)
    for restore in snapshots:
        restore()
