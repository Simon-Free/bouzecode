# Integration Wave 1 — Resolution Notes

## Merges Performed

| Branch | Strategy | Result |
|--------|----------|--------|
| `feat/mr1-engine-core` | fast-forward | Clean (1df5ed3→1675ac6) |
| `feat/mr2-web-v2` | ort (recursive) | Clean — no conflicts detected |
| `feat/mr7-demos-htmlrenderer-folderdesc` | ort (recursive) | Clean — no conflicts detected |
| `feat/mr3-voice` | ort (recursive) | Clean — no conflicts detected |
| `feat/mr9-telegram-proactive` | ort (recursive) | Clean — auto-merged pyproject.toml optional-deps |
| `feat/mr4-video` | ort (recursive) | Clean — no conflicts detected |
| `feat/mr6-plugin-skill-task-memory` | ort (recursive) | Clean — no conflicts detected |

## Conflict Resolutions

### pyproject.toml — duplicate `[tool.pytest.ini_options]`

MR1 added markers; MR2 added `pythonpath` and `addopts`. Git merged both without
conflict markers but produced **two** `[tool.pytest.ini_options]` sections (TOML
invalid). Resolved by merging into a single section:

```toml
[tool.pytest.ini_options]
pythonpath = ["src", "."]
addopts = "--import-mode=importlib"
testpaths = ["tests"]
markers = [
    "backend: agent-engine tests",
    "ui: terminal-UI tests",
    "web: Flask + Playwright web tests",
    "slow: fixture-target marker",
]
```

### conftest.py (root) vs tests/conftest.py

No actual conflict — both files coexist:
- `conftest.py` (root): ensures `src/` is at `sys.path[0]` before rootdir, purges
  stale `bouzecode` script module. Rootdir stays in path for flat legacy modules.
- `tests/conftest.py`: test fixtures (MR1).

sys.path order verified: `src` → rootdir (`.`).

## Port: `src/bouzecode/web/` (internal dependency)

`backend/tools/plan_mode.py` and `tools/interaction.py` import `bouzecode.web.ipc`.
The package was not part of MR1/MR2, so it was ported from the internal source
(`calypso/bouzecode/src/bouzecode/web/`) into `src/bouzecode/web/` (47 files,
dedicated commit `5fbacff`).

The legacy flat `web/` directory (bouzegui) remains untouched.

## Test Results

| Suite | Command | Result |
|-------|---------|--------|
| Main (post-MR7) | `python -m pytest tests/ -q` | 596 passed, 3 failed* |
| Main (post-MR3) | `python -m pytest tests/ -q` | 606 passed, 3 failed* |
| Main (post-MR9) | `python -m pytest tests/ -q` | 627 passed, 3 failed* |
| Main (post-MR4) | `python -m pytest tests/ -q` | 637 passed, 3 failed* |
| Main (post-MR6) | `python -m pytest tests/ -q` | 637 passed, 3 failed* |
| Web V2 | `python -m pytest tests/web_v2 src/bouzecode/web_v2 -q` | 55 passed |

\* Tolerated pre-existing failures (3):
- `tests/test_xml_docs.py::test_docs_include_a_parsable_xml_example` — XML doc generation drift
- `tests/test_plugin.py::TestAskUserQuestion::test_…` (×2) — fix in progress on feat/mr1-engine-core

## Environment Note

`BOUZECODE_WEB_IPC_DIR` must **not** be set when running tests in CLI mode; otherwise
`is_web_ipc_active()` returns `True` and `AskUserQuestion` raises `PausedForInput`
instead of falling through to terminal input.
