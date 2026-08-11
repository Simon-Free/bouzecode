# [desc] Pytest conftest: loads .env, blocks real LLM calls, isolates global state between tests. [/desc]
"""Bouzecode OSS test configuration.

Loads .env at collection time. Autouse fixtures block accidental real LLM calls
and isolate global state between tests.
"""
from __future__ import annotations

import functools
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
    config.addinivalue_line(
        "markers",
        "web: Flask web-UI tests (tests/web_v2/ and src/bouzecode/web_v2/tests/)",
    )
    config.addinivalue_line("markers", "slow: fixture-target marker for the test-runner tests")


# `tests/frontend/` does not exist in this repository — the web-UI tests live in
# `tests/web_v2/` and in `src/bouzecode/web_v2/tests/`. Both are now in `testpaths`,
# and both fragments are matched so `pytest -m web` selects the same set whether the
# whole suite runs or only one of the two trees is passed on the command line.
_MARKER_BY_PATH_FRAGMENT = (
    ("/tests/backend/", "backend"),
    ("/tests/ui/", "ui"),
    ("/tests/web_v2/", "web"),
    ("/web_v2/tests/", "web"),
)


def pytest_collection_modifyitems(config, items):
    """Auto-mark every test by the folder it lives in."""
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        for fragment, marker in _MARKER_BY_PATH_FRAGMENT:
            if fragment in path:
                item.add_marker(marker)
                break


from tests import repo_tree_guard

# Resolved once: `git ls-files` per test would cost 2800 subprocesses.
_WATCHED_PATHS = repo_tree_guard.watched_paths(_BOUZECODE_ROOT)


@pytest.fixture(autouse=True)
def _repo_working_tree_untouched():
    """Fail any test that writes into this checkout (see tests/repo_tree_guard)."""
    before = repo_tree_guard.snapshot(_WATCHED_PATHS)
    yield
    after = repo_tree_guard.snapshot(_WATCHED_PATHS)
    touched = [p for p in _WATCHED_PATHS if before[p] != after[p]]
    if not touched:
        return
    repo_tree_guard.revert(_BOUZECODE_ROOT, touched)
    pytest.fail(
        "this test wrote into the git-tracked working tree: "
        + ", ".join(str(p.relative_to(_BOUZECODE_ROOT)) for p in touched)
        + " — use the `agent_cwd` fixture so the agent runs in a tmp directory."
    )


@pytest.fixture
def agent_cwd(tmp_path, monkeypatch):
    """Run the agent from a scratch directory instead of this checkout.

    Tools that persist artifacts relative to `Path.cwd()` — plan mode writes
    `.nano_claude/plans/<session>.md` — otherwise edit the developer's repo.
    `_isolate_global_state` already restores the cwd; this picks the right one."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


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

    # `functools.wraps` is not cosmetic here: it sets `__wrapped__`, which is the
    # only way `inspect.unwrap()` can see the provider's real signature through the
    # gate. Without it every spy that mirrors `stream_anthropic` (see
    # tests/methodology_cache_e2e_helpers.assert_mirrors) compares itself against
    # `(*args, **kwargs)` and fails at fixture setup.
    @functools.wraps(_real)
    def _gated(*args, **kwargs):
        if not getattr(cch, "LIVE_API_ALLOWED", False):
            raise RuntimeError(
                "Real LLM call blocked: this test reached the live API without "
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
    # Le jeu des dossiers « écrits par cet agent » vit AUSSI longtemps que le process, et le
    # hook d'édition (context_manager.readme_stale) l'alimente à chaque Write d'un fichier de
    # code : tout test e2e qui écrit du code y dépose son dossier pour le reste du worker. Un
    # test ultérieur portant sur le même dossier se verrait alors servir « you edited this
    # folder yourself » au lieu d'une régénération. Les `_SELF_AUTHORED.clear()` semés à la
    # main dans tests/backend/agents_map/ étaient le pansement ; ceci est la plaie.
    _snap_collection("bouzecode.backend.tools.agents_map.serve", "_SELF_AUTHORED")
    yield
    os.chdir(_orig_cwd)
    for restore in snapshots:
        restore()
