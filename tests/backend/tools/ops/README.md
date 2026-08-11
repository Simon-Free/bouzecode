# tools/ops/

## Purpose

Covers two things in `bouzecode.backend.tools.ops`: the pytest output compaction in
`truncation.compact_pytest_output`, and how lenient the Edit and Read tools are with what
the model sends them.

The compaction file calls the function directly on sample pytest transcripts. The two
`_e2e` files run whole conversations through the `bouzecode()` harness with `MockLLM` and
assert on the tool results the agent got back.

## Usage

- `test_compact_pytest.py` — `compact_pytest_output` on sample transcripts: all green
  (plain and verbose), one and two failures, collection errors, warnings, and output that
  is not pytest at all. The verdict and the failing tests survive, the noise does not.
- `test_edit_leniency_e2e.py` — a missed Edit answers with which line diverges, and only
  a uniform re-indentation is repaired automatically.
- `test_read_param_synonyms_e2e.py` — Read accepts Snippet's line vocabulary when the
  conversion is exact, and refuses it when it is not.
- `test_shell_search_deferred.py` — `bash_handler(deferred=True)` queues the command on the
  context state instead of running it, and a plain call still runs it. It sat inside
  `src/bouzecode/backend/tools/ops/` — never collected, and shipped in the wheel.
