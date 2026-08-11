# tests/

Feature + CLI tests that drive the REAL CLI and hook (via subprocess) over temporary trees, plus mechanical map tests. LLM tests are marked `@pytest.mark.llm` and self-skip without API credentials.

---

## Module Reference

| File | Lines | Purpose |
|------|-------|---------|
| `conftest.py` | — | `REPO_ROOT`, `mini_tree` fixture (pkg/core.py, io_utils.py, sub/widget.py, ignored .venv), `run_cli` subprocess helper. |
| `_helpers.py` | — | `make_fresh()` — writes a README + coherent fresh lock for a folder. |
| `feature/test_detection.py` | — | 7 hash-detection tests (missing/stale/new/deleted/orphan/ignore-list). |
| `feature/test_contract.py` | — | Contract declares required sections; the real agent/README.md passes validate(). |
| `feature/test_regen.py` | — | 4 LLM regen tests (valid structure, clears stale, reflects rename, one call per stale folder). |
| `feature/test_hook.py` | — | 4 hook tests (code marks stale, README/non-code no-op, lock created if missing). |
| `feature/test_javascript_folders.py` | — | 4 tests: a `.js` folder classifies like a `.py` one, vendored code stays out of the walk. |
| `feature/test_map.py` | — | 4 mechanical map tests (purpose propagates, no dead links, root reachability, top-level listing). |
| `feature/test_end_to_end.py` | — | Full business flow (LLM): fresh → rename → hook → check KO → regen → check OK. |
| `cli/test_check_exit_codes.py` | — | Exit codes + --list-stale prints only paths. |
