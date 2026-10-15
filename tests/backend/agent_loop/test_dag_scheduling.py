"""DAG scheduling: alias resolution, rebuild survival, conservative pinning.

Regressions covered (both observed live in a demo session):
1. A depends_on referencing an alias the model never declared
   (tool_call_alias missing on the producer) used to be DROPPED silently,
   running the consumer in parallel with its producer — the exact race the
   dependency was meant to prevent.
2. _build_alias_map/_build_dag_levels used to .pop() the scheduling keys,
   destroying them on the first build. The pause/resume path
   (resume_paused → _complete_pending_tool_calls) rebuilds the DAG on the
   SAME dicts, so every dependency was silently lost on resume.
"""

from bouzecode.backend.agent.dag import _build_dag_levels


def _tc(call_id: str, name: str, **params):
    return {"id": call_id, "name": name, "input": dict(params)}


def test_alias_orders_consumer_after_producer():
    write = _tc("call_w1", "Write", file_path="a.py", content="x",
                tool_call_alias="w1")
    # Command deliberately does NOT mention the written file: we are testing
    # alias resolution alone, not the filename-based auto-injection fallback.
    bash = _tc("call_b1", "Bash", command="echo done", depends_on=["w1"])
    levels, deps = _build_dag_levels([write, bash])
    assert [[tc["name"] for tc in level] for level in levels] == [["Write"], ["Bash"]]
    assert deps["call_b1"] == {"call_w1"}


def test_unresolved_alias_pins_call_after_all_siblings():
    # Exact shape of the live incident: Bash declares depends_on=["w_inspect"]
    # but the Write never emitted tool_call_alias="w_inspect". The dependency
    # must NOT be dropped: the Bash runs after every other call of the turn.
    write = _tc("call_51b19cde", "Write", file_path="temp_inspect_session.py",
                content="print('ok')")
    bash = _tc("call_28a82de5", "Bash", command="echo done",
               depends_on=["w_inspect"])
    levels, deps = _build_dag_levels([write, bash])
    assert [[tc["name"] for tc in level] for level in levels] == [["Write"], ["Bash"]]
    assert deps["call_28a82de5"] >= {"call_51b19cde"}


def test_scheduling_keys_survive_rebuild():
    # Pause/resume rebuilds the DAG on the same dicts: dependencies and
    # levels must be identical on the second build.
    write = _tc("call_w1", "Write", file_path="a.py", content="x",
                tool_call_alias="w1")
    bash = _tc("call_b1", "Bash", command="echo done", depends_on=["w1"])
    first_levels, first_deps = _build_dag_levels([write, bash])
    second_levels, second_deps = _build_dag_levels([write, bash])
    assert first_deps == second_deps
    assert [[tc["id"] for tc in level] for level in first_levels] == \
           [[tc["id"] for tc in level] for level in second_levels]


def test_build_does_not_mutate_scheduling_keys():
    write = _tc("call_w1", "Write", file_path="a.py", content="x",
                tool_call_alias="w1")
    bash = _tc("call_b1", "Bash", command="echo done", depends_on=["w1"])
    _build_dag_levels([write, bash])
    # Keys stay in the input: execute_tool strips them at execution time.
    assert write["input"]["tool_call_alias"] == "w1"
    assert bash["input"]["depends_on"] == ["w1"]


def test_two_unresolved_dependencies_do_not_cycle():
    a = _tc("call_a", "Bash", command="echo a", depends_on=["ghost_a"])
    b = _tc("call_b", "Bash", command="echo b", depends_on=["ghost_b"])
    levels, deps = _build_dag_levels([a, b])
    # Terminates and every call is scheduled exactly once (no cycle deadlock).
    scheduled = [tc["id"] for level in levels for tc in level]
    assert sorted(scheduled) == ["call_a", "call_b"]
