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


def _announce_activity(config: dict, level: list[dict]) -> None:
    """Publie les outils qui DÉMARRENT, pour les observateurs hors du process (BouzéqUI).

    C'est le seul battement possible pendant l'exécution d'un outil, et il manquait. Les deux
    autres traces s'éteignent précisément là : `partial_stream.clear_partial` supprime le flux
    assistant dès que le LLM a fini de streamer, DONC avant que les outils tournent, et la
    session n'est sauvegardée qu'à la fin du tour. Entre les deux, un `Bash` de cinq minutes
    ne laissait rien : l'interface affichait « en cours » sans pouvoir dire de quoi, et un
    agent réellement bloqué était indiscernable d'un agent au travail (cas eac1f0bef295).

    Le rappel est optionnel et n'existe que sous BouzéqUI (`repl` l'installe) : en CLI il n'y a
    personne à informer, l'utilisateur voit le terminal."""
    activity_cb = config.get("_ipc_activity_cb")
    if activity_cb is None:
        return
    activity_cb([tc["name"] for tc in level])


CANCELLED_BY_USER = "Cancelled: interrupted by the user before this tool ran."


def _cancel_requested(config: dict) -> bool:
    """L'utilisateur a-t-il demandé l'arrêt du tour ? (SANS consommer sa demande)

    Le drapeau d'annulation n'était sondé QUE pendant le streaming LLM (`_interruptible_iter`)
    et en tête de tour. Un lot d'outils — c'est-à-dire la majeure partie d'un tour de travail —
    ne le regardait jamais : sous BouzéqUI, interrompre pendant les outils ne produisait rien,
    puis l'escalade de `/interrupt` tuait le process faute de réponse. Le Ctrl+C du TUI, lui,
    est un signal : il tombe n'importe où, y compris là.

    On PEEK (`_cancel_peek`) là où la boucle CONSOMME (`_cancel_check`) : consommer ici
    volerait la demande à la garde de tête de `loop.run`, qui est ce qui clôt réellement le
    tour (`close_reason='cancelled'`). Les outils cessent de partir, la boucle constate et
    rend la main. Absent en CLI (`repl` ne l'installe que sous BouzéqUI) : le TUI garde son
    signal, ce code ne le concerne pas."""
    peek = config.get("_cancel_peek")
    return bool(peek and peek())


def _mark_cancelled(tcs: list[dict], results: dict[str, str],
                    durations: dict[str, float]) -> None:
    """Donne un résultat aux outils qui ne partiront pas.

    Les laisser sans résultat casserait la session : l'assistant y porte des tool_calls dont
    l'API exige la réponse. Le motif est ÉCRIT, comme pour un plan rejeté — au tour suivant
    le modèle lit que l'utilisateur l'a coupé, au lieu de deviner un trou."""
    for tc in tcs:
        if tc["id"] not in results:
            results[tc["id"]] = CANCELLED_BY_USER
            durations[tc["id"]] = 0.0


def _execute_level(
    level: list[dict],
    results: dict[str, str],
    durations: dict[str, float],
    config: dict,
) -> None:
    from ..core.tool_registry import is_concurrent_safe

    # Frontière d'interruption : entre deux NIVEAUX du DAG, donc avant chaque nouvelle vague
    # d'outils. Un outil DÉJÀ parti va jusqu'au bout (un `Bash` de cinq minutes n'est pas
    # rattrapable d'ici) — l'annulation mord au prochain outil, pas au prochain bytecode.
    if _cancel_requested(config):
        _mark_cancelled(level, results, durations)
        return

    _announce_activity(config, level)

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

    for index, tc in enumerate(sequential_tcs):
        # Seconde frontière : les outils séquentiels d'un même niveau partent l'un APRÈS
        # l'autre (deux `Bash` à la suite, p.ex.). Sans ce test, interrompre au premier
        # laissait quand même tourner tous les suivants.
        if _cancel_requested(config):
            _mark_cancelled(sequential_tcs[index:], results, durations)
            return
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
