# [desc] Detect missing Methodology/Snippet calls after thinking blocks or Read tool results [/desc]
"""Enforcement hooks — detect missing Methodology/Snippet calls after thinking/reading."""

import re

# Builtins whose results are snippeted by file_path (not registry-flagged).
_FILE_SNIPPET_TOOLS = {"Read", "Skill"}


def _is_tool_id_snippetable(tool_name: str | None) -> bool:
    """True if *tool_name* is a registered tool whose result is snippeted by tool_id."""
    if not tool_name:
        return False
    from ..core.tool_registry import get_tool
    tool = get_tool(tool_name)
    return bool(
        tool
        and getattr(tool, "snippetable", False)
        and getattr(tool, "snippet_key", "tool_id") == "tool_id"
    )


def _snippet_coverage(tool_calls: list[dict]) -> tuple[set, bool]:
    """Return (covered_keys, discard_all) from the Snippet calls in *tool_calls*.

    A key is either a file_path (file-keyed snippet) or a tool_id (inline result).
    """
    keys = set()
    discard_all = False
    for tc in tool_calls or []:
        if tc.get("name") != "Snippet":
            continue
        inp = tc.get("input", {}) or {}
        fp = inp.get("file_path", "")
        tid = inp.get("tool_id", "")
        if inp.get("discard") and not fp and not tid:
            discard_all = True
        if fp:
            keys.add(fp)
        if tid:
            keys.add(tid)
    return keys, discard_all


def get_unsnippeted_reads(messages: list[dict]) -> list[dict]:
    """Return [{key, kind, line_count, tool_name}] for snippetable results not covered.

    Scans the LAST assistant turn's tool calls. Tracks two kinds of snippetable
    result: Read/Skill (file-keyed) and tool_id-snippetable tools (registry-flagged,
    inline results wrapped on the wire). For each, checks whether a Snippet call
    (matching file_path/tool_id, or discard) exists in the same batch or a following
    assistant response.

    Returns empty list (falsy) when all snippetable results are covered.
    """
    if len(messages) < 2:
        return []

    last_assistant_idx = None
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") == "assistant" and any(
            tc.get("name") in _FILE_SNIPPET_TOOLS or _is_tool_id_snippetable(tc.get("name"))
            for tc in msg.get("tool_calls", [])
        ):
            last_assistant_idx = i
            break

    if last_assistant_idx is None:
        return []

    tool_calls = messages[last_assistant_idx].get("tool_calls", [])

    # tracked: tool_call_id -> {kind, key, tool_name}; key may be filled later (Skill)
    tracked: dict[str, dict] = {}
    for tc in tool_calls:
        name = tc.get("name")
        if name == "Read":
            key = (tc.get("input", {}) or {}).get("file_path", "unknown")
            tracked[tc["id"]] = {"kind": "file", "key": key, "tool_name": name}
        elif name == "Skill":
            # file_path is extracted from the tool_result content later
            tracked[tc["id"]] = {"kind": "file", "key": None, "tool_name": name}
        elif _is_tool_id_snippetable(name):
            tracked[tc["id"]] = {"kind": "tool_id", "key": tc["id"], "tool_name": name}

    if not tracked:
        return []

    # Timing guard: when the read-bearing batch CLOSED the turn (emitted a
    # Methodology call) but the model hasn't taken its next turn yet, defer —
    # it Snippets the previous turn's reads at the START of the next turn, so
    # enforcing now would be premature. Real loop turns always carry Methodology,
    # so this keeps production timing intact; a Methodology-less batch (only seen
    # in isolated detector tests / malformed turns) is reported immediately.
    batch_has_methodology = any(tc.get("name") == "Methodology" for tc in tool_calls)
    has_subsequent_assistant = any(
        msg.get("role") == "assistant"
        for msg in messages[last_assistant_idx + 1:]
    )
    if batch_has_methodology and not has_subsequent_assistant:
        return []

    # Snippet coverage from the SAME assistant message (same batch)
    covered_keys, discard_all = _snippet_coverage(tool_calls)
    if discard_all:
        return []
    for tid in [t for t, info in tracked.items() if info["key"] in covered_keys]:
        del tracked[tid]
    if not tracked:
        return []

    # Walk subsequent messages: count result lines, resolve Skill paths, drop covered.
    line_counts: dict[str, int] = {}
    for msg in messages[last_assistant_idx + 1:]:
        if msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id")
            if tc_id in tracked:
                content = msg.get("content", "")
                line_counts[tc_id] = content.count("\n") + (1 if content else 0)
                info = tracked[tc_id]
                # For Skill results, extract file_path from "[Skill: name | file: /path]"
                if info["kind"] == "file" and not info["key"]:
                    m = re.search(r'\[Skill: .+? \| file: (.+?)\]', content)
                    if m:
                        info["key"] = m.group(1)
                    else:
                        del tracked[tc_id]
                        line_counts.pop(tc_id, None)
        elif msg.get("role") == "assistant":
            covered_keys, discard_all = _snippet_coverage(msg.get("tool_calls", []))
            if discard_all:
                return []
            for tid in [t for t, info in tracked.items() if info["key"] in covered_keys]:
                del tracked[tid]
                line_counts.pop(tid, None)
            if not tracked:
                break

    if not tracked:
        return []

    # Only include results that have been executed (tool_result exists)
    # AND that meet the minimum line threshold for snippet enforcement.
    # `file_path` mirrors `key` for back-compat with legacy consumers that read it;
    # `key`/`kind` are the current shape (file paths and inline tool_ids alike).
    from ..agent.snippet_wire import SNIPPET_MIN_LINES

    result = []
    for tc_id, info in tracked.items():
        if tc_id not in line_counts:
            continue
        if line_counts[tc_id] < SNIPPET_MIN_LINES:
            continue
        result.append({
            "key": info["key"],
            "kind": info["kind"],
            "file_path": info["key"],
            "line_count": line_counts[tc_id],
            "tool_name": info["tool_name"],
        })
    return result


def has_unsnippeted_reads(messages: list[dict]) -> bool:
    """Backward-compatible wrapper: True if any snippetable result lacks a Snippet."""
    return bool(get_unsnippeted_reads(messages))


def _had_thinking(tool_calls: list[dict], messages: list[dict]) -> bool:
    """Check if the current assistant turn included a thinking block."""
    if not messages:
        return False
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "thinking":
                        return True
            elif isinstance(content, str) and "<thinking>" in content:
                return True
            break
    return False


def check_test_enforcement(state, config: dict) -> str | None:
    """Check that RunPythonTest was called at least once in the session.

    Returns warning string if no test was run, None if OK.
    Configurable via config["enforce_tests"] (default True).
    """
    if not config.get("enforce_tests", True):
        return None
    tool_messages = [m for m in state.messages if m.get("role") == "tool"]
    ran_test = any(m.get("name") == "RunPythonTest" for m in tool_messages)
    if ran_test:
        return None
    return (
        "⚠️ TEST ENFORCEMENT: You have not run any tests (RunPythonTest) this session. "
        "Every feature or bug fix MUST include tests. Call RunPythonTest before finishing. "
        "If this is intentional (e.g. pure documentation or config change), "
        "add enforce_tests: false to your config."
    )


def check_enforcement(tool_calls: list[dict], previous_had_unsnippeted_reads=None,
                      unsnippeted_reads: list[dict] | None = None) -> str | None:
    """Check if model complied with Methodology+Snippet rules.

    Args:
        tool_calls: The tool calls the model just emitted.
        previous_had_unsnippeted_reads: DEPRECATED bool — use unsnippeted_reads instead.
        unsnippeted_reads: List of {key, kind, line_count, tool_name} from get_unsnippeted_reads().

    Returns warning string if non-compliant, None if OK.
    """
    tool_names = {tc.get("name") for tc in tool_calls} if tool_calls else set()

    # Resolve unsnippeted info (support both old bool and new list API)
    if unsnippeted_reads is None and previous_had_unsnippeted_reads:
        unsnippeted_reads = [{"key": "unknown", "kind": "file", "line_count": 0}]
    elif unsnippeted_reads is None:
        unsnippeted_reads = []

    has_methodology = "Methodology" in tool_names

    # Per-key Snippet coverage (file_path or tool_id); discard-all covers everything.
    snippeted_keys, discard_all = _snippet_coverage(tool_calls)

    # Filter unsnippeted_reads to only those NOT covered by a Snippet call this turn.
    # Accept both the new {key, kind} shape and the legacy {file_path} shape.
    uncovered_reads = [] if discard_all else [
        r for r in unsnippeted_reads
        if (r.get("key") or r.get("file_path")) not in snippeted_keys
    ]

    # Determine violations
    missing_methodology = not has_methodology
    missing_snippets = bool(uncovered_reads)

    if not missing_methodology and not missing_snippets:
        return None

    parts = []

    # Different messages depending on violation type
    if missing_methodology and not missing_snippets:
        parts.append(
            "⚠️ ENFORCEMENT: You MUST emit a Methodology call every turn. "
            "Your thinking is lost next turn — distill key findings, decisions, "
            "and next steps into Methodology now."
        )
    elif missing_snippets and not missing_methodology:
        parts.append(
            "⚠️ ENFORCEMENT: Your PREVIOUS turn received Read/Skill results that you did NOT Snippet. "
            "For every Read or Skill result you receive, you MUST either save important regions with "
            "Snippet(file_path, ranges, label) or explicitly discard with "
            "Snippet(discard=true, file_path=\"...\"). "
        )
    else:
        parts.append(
            "⚠️ ENFORCEMENT: You are missing BOTH Methodology and Snippet calls. "
            "You MUST emit Methodology every turn AND Snippet for every Read/Skill result received. "
        )

    if uncovered_reads:
        file_list = ", ".join(
            f"`{r.get('key') or r.get('file_path')}` ({r['line_count']} lines)" if r.get('line_count')
            else f"`{r.get('key') or r.get('file_path')}`"
            for r in uncovered_reads
        )
        parts.append(f"Files that need Snippet: {file_list}. ")

    if tool_calls:
        parts.append(
            "Your previous tool calls above are already recorded — they WILL be executed "
            "after you comply. Do NOT repeat them. Emit ONLY the missing call(s) now."
        )
    else:
        parts.append(
            "NO tool call from your previous turn was recorded — if you emitted "
            "<tool_use> blocks, they failed to parse and were NOT executed. Emit the "
            "missing call(s) now, and RE-EMIT your intended tool calls with them "
            "(smaller batches parse more reliably)."
        )

    return "".join(parts)
