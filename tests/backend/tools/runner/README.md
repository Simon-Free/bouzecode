# tools/runner/

## Purpose

Covers the `RunPythonTest` tool in `bouzecode.backend.tools.ops.test_runner`: running a
pytest file in a subprocess, streaming its output, and reporting progress and a pass/fail
summary.

Three approaches sit here. `_stream_with_progress` is fed the exact lines pytest prints,
hermetically. Other files call `run_python_test` for real, which spawns a nested pytest —
those pay a subprocess and are serialised by the conftest lock. Conversation tests use
the `bouzecode()` harness (`MockLLM`, or a real key via `require_api_key`) and read the
summary out of the `tool_result`. Two files in this folder are not tests of the runner
but the targets it runs.

## Usage

- `conftest.py` — serialises every test that launches a nested pytest: a lock file in the
  OS temp dir, one holder at a time across all xdist workers, with a bounded wait and a
  staleness takeover so the suite always finishes.
- `test_tqdm_progress_e2e.py` — `_stream_with_progress` recognises the "collected N
  items" line and per-test result lines (plain and xdist) and drives a tqdm bar on
  stderr, without spawning pytest.
- `test_test_runner_progress.py` — the progress regexes (`_COLLECTED_RE`,
  `_XDIST_COLLECTED_RE`, `_XDIST_RESULT_RE`, `_STANDARD_RESULT_RE`) and an end-to-end
  execution report.
- `test_e2e_run_python_test.py` — direct `run_python_test` calls on the trivial targets,
  plus the model reaching the tool through the real XML pipeline.
- `test_run_summary_e2e.py` — a conversation where the model runs `RunPythonTest` on real
  mini test files and the pass/fail summary appears in the tool result.
- `test_trivial_runner.py` — an always-passing target for the runs above.
- `test_trivial_runner_slow.py` — a `slow`-marked sleeping target, used for marker
  filtering and timeouts.
