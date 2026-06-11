# [desc] Minimal-wire pipeline for methodology-centric architecture: keep only the last asst+tools batch, user msgs, and Write/Edit acks. Prior assistant messages dropped entirely. [/desc]
"""Build the on-wire payload under the methodology-centric architecture.

The contract communicated to the model: every persistent fact lives in the
methodology system block (cached). At each turn the wire contains only:
- The LATEST user message (earlier user msgs are already in methodology as
  ## User blocks, keeping them on the wire is pure duplication)
- The last assistant turn's tool_results (the assistant message itself — prose
  + tool_use XML — is dropped; only its results carry forward)
- Write/Edit tool_results from prior turns, compacted to a one-line ack so
  the model can confirm the file change succeeded without re-paying the diff
- Everything else from prior turns: dropped entirely (assistant prose,
  assistant tool_use XML, and non-Write/Edit tool_results)

Dropping prior wire bytes (rather than stripping/rewriting them) is
load-bearing for the prompt cache: any post-hoc rewrite of an earlier byte
invalidates the cache from that point on.
"""
from __future__ import annotations

_DESTRUCTION_BANNER = (
    "[SYSTEM] This tool_result will be destroyed at the next user turn "
    "unless you snippet it or stash a note with Methodology.\n\n"
)


def _last_asst_with_tools_idx(messages: list[dict]) -> int:
    """Index of the asst-with-tool_calls whose batch is still 'live' for this
    LLM call. A batch is live only when it sits at the tail of the message
    list followed by nothing or only its own tool_results. If a later user
    msg or no-tools asst has arrived, the batch is finished and gets pruned
    like any other prior batch.
    """
    j = len(messages) - 1
    while j >= 0 and messages[j].get("role") == "tool":
        j -= 1
    if j < 0:
        return -1
    msg = messages[j]
    if msg.get("role") == "assistant" and msg.get("tool_calls"):
        return j
    # Enforcement pattern: user msg immediately after assistant-with-tools
    # (no tool_results in between). The assistant batch is still "live".
    if msg.get("role") == "user" and j > 0:
        prev = messages[j - 1]
        if prev.get("role") == "assistant" and prev.get("tool_calls"):
            return j - 1
    return -1


def _build_tool_name_index(messages: list[dict]) -> dict[str, str]:
    """Map tool_call_id -> tool_name across the full message history."""
    index: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            tid = tc.get("id")
            if tid:
                index[tid] = tc.get("name", "")
    return index


def _build_file_path_index(messages: list[dict]) -> dict[str, str]:
    """Map tool_call_id -> file_path for Read/Skill calls (used for file snippet wrapping)."""
    index: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            name = tc.get("name")
            if name in ("Read", "Skill"):
                tid = tc.get("id")
                fp = (tc.get("input") or {}).get("file_path", "")
                if tid and fp:
                    index[tid] = fp
    return index


def _compact_write_edit_result(content: str, tool_name: str, tool_call_id: str) -> str:
    """Compact a Write/Edit tool_result to a one-line ack (success) or full
    error message. Keeps just enough info for the model to know the file
    operation worked or to read the failure reason."""
    if not content:
        return f"[{tool_name} {tool_call_id} — empty result]"
    first = content.lstrip().splitlines()[0] if content.strip() else ""
    if first.startswith("Error") or "Error:" in first:
        return content  # keep full error verbatim
    if first.startswith(("Created ", "No changes ", "File updated", "Changes applied")):
        return f"[{tool_name} {tool_call_id} OK — {first}]"
    return f"[{tool_name} {tool_call_id} — {first[:120]}]"


def _last_user_idx(messages: list[dict]) -> int:
    """Index of the latest user message. Earlier user messages already live
    in the methodology (## User blocks), so only this one needs to appear
    on the wire to satisfy the API's leading-user-message requirement."""
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            return i
    return -1


_INTERRUPTED_BANNER = (
    "[SYSTEM] The user interrupted your previous response (Ctrl+C). "
    "Below is what you had generated before the interruption — "
    "the user wants to redirect or comment on it:\n\n"
)


def build_minimal_payload(messages: list[dict]) -> list[dict]:
    """Apply the methodology-centric pruning: only tool_results from the live
    batch reach the wire. The assistant message (prose + tool_use XML) is
    dropped — methodology + tool_results already convey everything needed.
    """
    last_batch = _last_asst_with_tools_idx(messages)
    latest_user = _last_user_idx(messages)

    # Detect _interrupted message just before latest user message
    interrupted_content = None
    if latest_user > 0:
        prev = messages[latest_user - 1]
        if prev.get("_interrupted"):
            interrupted_content = prev.get("content", "")

    if last_batch < 0:
        if latest_user >= 0:
            user_msg = dict(messages[latest_user])
            if interrupted_content:
                user_msg["content"] = (
                    _INTERRUPTED_BANNER + interrupted_content
                    + "\n\n---\n\n" + (user_msg.get("content", "") or "")
                )
            return [user_msg]
        return []

    # Drop the live-batch assistant message itself (its prose + tool_use XML are
    # redundant — methodology + tool_results convey everything). Keep only what
    # follows it (tool_results, the enforcement/next user msg). The Ctrl+C case is
    # handled separately via interrupted_content, which prefixes the user message.
    # Snippetable results are wrapped with "==== A SNIPPETER ====" markers:
    # - tool_id-keyed (Grep, GetFolderDescription, WebFetch): id: tool_id=...
    # - file-keyed (Read, Skill): id: file=<path>
    # The first non-snippetable result gets the destruction banner instead.
    from .snippet_wire import (
        is_snippetable_tool_id, wrap_snippetable,
        is_file_snippetable, wrap_file_snippetable,
        SNIPPET_MIN_LINES, _line_count,
    )

    result: list[dict] = []
    banner_injected = False
    name_index = _build_tool_name_index(messages)
    file_path_index = _build_file_path_index(messages)
    for i in range(last_batch + 1, len(messages)):
        msg = messages[i]
        if msg.get("_interrupted"):
            continue  # Skip _interrupted from wire (injected as prefix instead)
        if msg.get("role") == "tool":
            tool_id = msg.get("tool_call_id")
            tool_name = name_index.get(tool_id)
            content = msg.get("content", "") or ""
            # For snippetable tools, only wrap if content meets line threshold;
            # small results fall through to the normal banner/passthrough path.
            if is_snippetable_tool_id(tool_name) and _line_count(content) >= SNIPPET_MIN_LINES:
                cleaned = dict(msg)
                cleaned["content"] = wrap_snippetable(content, tool_id)
                result.append(cleaned)
            elif is_file_snippetable(tool_name) and file_path_index.get(tool_id) and _line_count(content) >= SNIPPET_MIN_LINES:
                cleaned = dict(msg)
                cleaned["content"] = wrap_file_snippetable(
                    content, file_path_index[tool_id]
                )
                result.append(cleaned)
            elif not banner_injected:
                cleaned = dict(msg)
                cleaned["content"] = _DESTRUCTION_BANNER + content
                result.append(cleaned)
                banner_injected = True
            else:
                result.append(msg)
        elif msg.get("role") == "user" and interrupted_content and i == latest_user:
            injected = dict(msg)
            injected["content"] = (
                _INTERRUPTED_BANNER + interrupted_content
                + "\n\n---\n\n" + (msg.get("content", "") or "")
            )
            result.append(injected)
        else:
            result.append(msg)

    # The wire must begin with a user/assistant message — never a bare
    # tool_result (Anthropic rejects that). The methodology-centric design keeps
    # the earlier user message OUT of the wire (it lives in the methodology
    # system block), so when the batch's tool_results would lead, prepend a
    # minimal assistant stub. In the enforcement pattern a trailing user message
    # already provides a valid leading role, so no stub is added there.
    if not result or result[0].get("role") == "tool":
        result.insert(0, {"role": "assistant", "content": "."})

    return result


# ── Thinking block stripping ────────────────────────────────────────────────


def _strip_thinking_blocks(text: str) -> str:
    """Remove <thinking>...</thinking> blocks (inline or multiline).

    Delegates to thinking_parser.strip_thinking_tags for single-source-of-truth.
    """
    from .thinking_parser import strip_thinking_tags
    return strip_thinking_tags(text)


def _strip_thinking_from_messages(messages: list) -> list:
    """Remove thinking blocks from assistant message content.

    Non-destructive: returns a new list with new dicts where needed.
    Handles both string and list-of-blocks content formats.
    """
    result = []
    for msg in messages:
        if msg.get("role") != "assistant":
            result.append(msg)
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and "<thinking>" in content:
            cleaned = _strip_thinking_blocks(content)
            result.append({**msg, "content": cleaned or "."})
        elif isinstance(content, list):
            new_blocks = []
            changed = False
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text" and "<thinking>" in block.get("text", ""):
                    cleaned = _strip_thinking_blocks(block["text"])
                    new_blocks.append({**block, "text": cleaned or "."})
                    changed = True
                else:
                    new_blocks.append(block)
            result.append({**msg, "content": new_blocks} if changed else msg)
        else:
            result.append(msg)
    return result


def build_messages_for_api(state, config: dict) -> list:
    """Methodology-centric pipeline: strip thinking then prune to minimal wire payload."""
    result = list(state.messages)
    result = _strip_thinking_from_messages(result)
    result = build_minimal_payload(result)
    return result
