# dag/

## Purpose
Tests of `agent.dag` — how a parallel tool batch is turned into dependency levels
(`_build_dag_levels`, `_coerce_list`) and executed (`_execute_level`,
`CANCELLED_BY_USER`), plus the two upstream stages that feed it:
`xml_tool_protocol.parser.XmlToolStreamParser` and `agent.id_uniquify.uniquify_tool_call_ids`.
Unit tests use fake tools with a timestamped call log; the ordering, denial and
interruption behaviours are driven as real conversations.

## Usage
- `test_dag_concurrency.py` — `concurrent_safe` tools overlap inside a level, sequential ones never do, and a mixed level runs the parallel part first.
- `test_dag_depends_on.py` — `_coerce_list` on lists and strings, and the auto-injected Write to Bash dependency.
- `test_dag_depends_on_e2e.py` — a conversation writes a script and runs it: explicit `depends_on`, plain-string alias, auto-injection when the Bash is listed first, basename matching, and no false positive on a different file.
- `test_dag_silent_drops.py` — three paths where a dependency could be dropped without a word: scheduling attributes on the XML tag, JSON-string `depends_on` surviving id uniquification, comma-separated and single-quoted lists, and a logged warning for an unresolved reference.
- `test_denial_cascade_e2e.py` — a denied call cancels its dependents whatever syntax they used; denial is produced through plan mode, so the harness's force-permit patch is deliberately not used.
- `test_interrupt_stops_tool_batch_e2e.py` — a `cancel.flag` appearing in the IPC dir mid-batch stops the following tools and later levels, marks them `CANCELLED_BY_USER`, ends the turn and pays no further LLM round trip.
