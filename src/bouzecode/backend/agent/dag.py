# [desc] Builds a dependency DAG from tool calls and executes them level-by-level with parallelism. [/desc]
from __future__ import annotations

import ast
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from ..tools import execute_tool


def _coerce_list(val) -> list:
    """Coerce a value to a list — handles JSON strings, Python repr, and comma-separated strings."""
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        val = val.strip()
        if val.startswith("["):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass
            # Fallback: handle Python-repr single quotes like "['t1', 't2']"
            try:
                parsed = ast.literal_eval(val)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed]
            except (ValueError, SyntaxError):
                pass
        if "," in val:
            return [p.strip() for p in val.split(",") if p.strip()]
        if val:
            return [val]
    return []


def _build_alias_map(tool_calls: list[dict]) -> dict[str, str]:
    alias_to_id: dict[str, str] = {}
    for tc in tool_calls:
        alias = tc["input"].pop("tool_call_alias", None)
        if alias:
            alias_to_id[alias] = tc["id"]
    return alias_to_id


def _build_dag_levels(tool_calls: list[dict]) -> tuple[list[list[dict]], dict[str, set[str]]]:
    """Return (levels, deps). Levels order tcs by dependency; deps maps tc_id → its prerequisites."""
    if not tool_calls:
        return [], {}

    by_id: dict[str, dict] = {tc["id"]: tc for tc in tool_calls}
    tc_ids_in_turn = set(by_id.keys())

    alias_to_id = _build_alias_map(tool_calls)

    deps: dict[str, set[str]] = {}
    for tc in tool_calls:
        raw = _coerce_list(tc["input"].pop("depends_on", None))
        resolved = [alias_to_id.get(d, d) for d in raw]
        valid = {d for d in resolved if d in tc_ids_in_turn}
        dropped = [d for d in resolved if d not in tc_ids_in_turn]
        if dropped:
            print(
                f"[dag] dropped unresolvable depends_on for {tc['name']}({tc['id']}): "
                f"{dropped} — available IDs: {sorted(tc_ids_in_turn)}, "
                f"aliases: {sorted(alias_to_id.keys())}",
                file=sys.stderr,
            )
        deps[tc["id"]] = valid

    _add_implicit_write_deps(tool_calls, deps)
    _inject_write_bash_deps(tool_calls, deps, alias_to_id)

    remaining = set(by_id.keys())
    ordered_ids = [tc["id"] for tc in tool_calls]  # preserve batch order within a level
    levels: list[list[dict]] = []
    while remaining:
        ready = {nid for nid in remaining
                 if not (deps.get(nid, set()) & remaining)}
        if not ready:
            levels.append([by_id[nid] for nid in ordered_ids if nid in remaining])
            break
        levels.append([by_id[nid] for nid in ordered_ids if nid in ready])
        remaining -= ready
    return levels, deps


def _compute_downstream(deps: dict[str, set[str]], seed_ids: set[str]) -> set[str]:
    """Return seed_ids plus every tc_id transitively depending on any seed."""
    dependents: dict[str, set[str]] = {}
    for tc_id, prereqs in deps.items():
        for prereq in prereqs:
            dependents.setdefault(prereq, set()).add(tc_id)

    downstream = set(seed_ids)
    frontier = list(seed_ids)
    while frontier:
        node = frontier.pop()
        for child in dependents.get(node, ()):
            if child not in downstream:
                downstream.add(child)
                frontier.append(child)
    return downstream


def _add_implicit_write_deps(
    tool_calls: list[dict],
    deps: dict[str, set[str]],
) -> None:
    last_write: dict[str, str] = {}
    for tc in tool_calls:
        if tc["name"] not in ("Write", "Edit", "NotebookEdit"):
            continue
        fp = os.path.normpath(tc["input"].get("file_path", tc["input"].get("notebook_path", "")))
        if not fp:
            continue
        prev = last_write.get(fp)
        if prev is not None:
            deps.setdefault(tc["id"], set()).add(prev)
        last_write[fp] = tc["id"]


def _inject_write_bash_deps(
    tool_calls: list[dict],
    deps: dict[str, set[str]],
    alias_to_id: dict[str, str],
) -> None:
    """Auto-inject deps when a Bash command references a file written by a Write in the same turn.

    Defense in depth: even if the model forgets depends_on, we detect the pattern
    and add the dependency so the Bash waits for the Write to complete.
    """
    write_map: dict[str, str] = {}  # normalized filename -> tc_id
    for tc in tool_calls:
        if tc["name"] not in ("Write", "Edit", "NotebookEdit"):
            continue
        fp = tc["input"].get("file_path", tc["input"].get("notebook_path", ""))
        if fp:
            fname = os.path.basename(fp)
            if fname:
                write_map[fname] = tc["id"]

    if not write_map:
        return

    all_tc_ids = {tc["id"] for tc in tool_calls}
    for tc in tool_calls:
        if tc["name"] != "Bash":
            continue
        cmd = tc["input"].get("command", "")
        existing = deps.get(tc["id"], set())
        for fname, write_id in write_map.items():
            if fname in cmd and write_id not in existing and write_id in all_tc_ids:
                deps.setdefault(tc["id"], set()).add(write_id)
                print(
                    f"[dag] auto-injected dependency: Bash({tc['id']}) "
                    f"now depends on Write({write_id}) for file '{fname}'",
                    file=sys.stderr,
                )


def _execute_level(
    level: list[dict],
    results: dict[str, str],
    durations: dict[str, float],
    config: dict,
) -> None:
    from ..core.tool_registry import is_concurrent_safe

    if len(level) == 1:
        tc = level[0]
        t0 = time.monotonic()
        results[tc["id"]] = execute_tool(
            tc["name"], tc["input"],
            permission_mode="accept-all", config=config)
        durations[tc["id"]] = time.monotonic() - t0
        return

    parallel_tcs = [tc for tc in level if is_concurrent_safe(tc["name"])]
    sequential_tcs = [tc for tc in level if not is_concurrent_safe(tc["name"])]

    if parallel_tcs:
        _run_parallel(parallel_tcs, results, durations, config)

    for tc in sequential_tcs:
        t0 = time.monotonic()
        results[tc["id"]] = execute_tool(
            tc["name"], tc["input"],
            permission_mode="accept-all", config=config)
        durations[tc["id"]] = time.monotonic() - t0


def _run_parallel(
    tcs: list[dict],
    results: dict[str, str],
    durations: dict[str, float],
    config: dict,
) -> None:
    if len(tcs) == 1:
        tc = tcs[0]
        t0 = time.monotonic()
        results[tc["id"]] = execute_tool(
            tc["name"], tc["input"],
            permission_mode="accept-all", config=config)
        durations[tc["id"]] = time.monotonic() - t0
        return

    pool = ThreadPoolExecutor(max_workers=len(tcs))
    start_times: dict[str, float] = {}
    for tc in tcs:
        start_times[tc["id"]] = time.monotonic()
    futures = {
        pool.submit(execute_tool, tc["name"], tc["input"],
                    "accept-all", None, config): tc
        for tc in tcs
    }
    try:
        remaining_futs = set(futures)
        while remaining_futs:
            newly_done = {f for f in remaining_futs if f.done()}
            for fut in newly_done:
                tc = futures[fut]
                results[tc["id"]] = fut.result()
                durations[tc["id"]] = time.monotonic() - start_times[tc["id"]]
            remaining_futs -= newly_done
            if remaining_futs:
                time.sleep(0.1)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
