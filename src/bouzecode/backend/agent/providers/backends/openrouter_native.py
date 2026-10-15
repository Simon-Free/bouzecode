# [desc] Converters for OpenRouter native function-calling: tool schemas, message format, streamed tool_call deltas. [/desc]
"""Native (OpenAI function-calling) helpers for the OpenRouter backend.

Weaker models hand-write XML tool calls unreliably (unclosed blocks, self-closing
params, CDATA mistakes). Native function-calling sends tools via the API `tools`
param and receives structured `tool_calls` deltas, removing that whole failure
class. These helpers convert to/from the neutral message format the agent loop uses.
"""
from __future__ import annotations
import json

from ..conversion import sanitize_messages

# Type seul : le sens de ces deux paramètres est dit une fois dans le noyau (voir
# core.tool_registry._SCHEDULING_PROPS).
_SCHEDULING_PROPS = {
    "depends_on": {"type": "array", "items": {"type": "string"}},
    "tool_call_alias": {"type": "string"},
}


def tool_schemas_to_openai(tool_schemas: list) -> list:
    tools = []
    for schema in tool_schemas or []:
        params = dict(schema.get("input_schema") or {})
        params.setdefault("type", "object")
        props = dict(params.get("properties") or {})
        for name, spec in _SCHEDULING_PROPS.items():
            props.setdefault(name, spec)
        params["properties"] = props
        tools.append({
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema.get("description", ""),
                "parameters": params,
            },
        })
    return tools


def _content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return str(content)


def _image_part(block: dict) -> dict:
    """Bloc image neutre (format Anthropic, base64) → partie `image_url` en data URI."""
    source = block.get("source") or {}
    url = f"data:{source.get('media_type') or 'image/png'};base64,{source.get('data', '')}"
    return {"type": "image_url", "image_url": {"url": url}}


def _text_part(block: dict, keep_cache: bool) -> dict:
    part = {"type": "text", "text": block.get("text", "")}
    if keep_cache and block.get("cache_control"):
        part["cache_control"] = block["cache_control"]
    return part


def user_content(content, keep_cache: bool = False):
    """Contenu d'un message user : du texte, ou des parties multimodales OpenAI s'il porte des
    images (ImageQuestion). Aplatir en texte, comme avant, perdait l'image en silence.

    Parties à `cache_control` (la note en <working_notes>) : gardées en parties si la route
    les transmet (`keep_cache`, Claude via LiteLLM/OpenRouter), sinon recollées SANS
    séparateur — elles portent les leurs, et le texte du tour N reste un préfixe du N+1."""
    blocs = [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
    cached = any(b.get("cache_control") for b in blocs)
    if any(b.get("type") == "image" for b in blocs) or (cached and keep_cache):
        return [_image_part(b) if b.get("type") == "image" else _text_part(b, keep_cache)
                for b in blocs if b.get("type") in ("image", "text")]
    if cached:
        return "".join(b.get("text", "") for b in blocs if b.get("type") == "text")
    return _content_to_text(content)


def messages_to_openai_native(messages: list, system: str, keep_cache: bool = False) -> list:
    msgs = sanitize_messages(messages)
    out = [{"role": "system", "content": system}]
    i = 0
    while i < len(msgs):
        m = msgs[i]
        role = m.get("role")
        if role == "user":
            out.append({"role": "user", "content": user_content(m["content"], keep_cache)})
            i += 1
        elif role == "assistant":
            entry = {
                "role": "assistant",
                "content": _content_to_text(m.get("content", "")) or None,
            }
            explicit = list(m.get("tool_calls", []) or [])
            i += 1
            tool_msgs = []
            while i < len(msgs) and msgs[i].get("role") == "tool":
                tool_msgs.append(msgs[i])
                i += 1
            # The minimal-wire (build_minimal_payload) drops the assistant message
            # that owned the tool_calls and keeps only its tool_results, inserting a
            # bare "." stub. That orphans the results: the strict OpenAI/Azure
            # protocol rejects a tool result whose tool_call_id has no matching
            # assistant tool_call ("No tool call found for function call output").
            # Synthesize the missing tool_calls from the results so every id pairs, with the
            # real arguments the minimal wire left on each result (`call_input`): a history of
            # `{}` calls taught the model to emit empty batches (see minimal_payload).
            declared = {tc.get("id") for tc in explicit}
            synthesized = []
            for tm in tool_msgs:
                tid = tm.get("tool_call_id")
                if tid and tid not in declared:
                    synthesized.append({"id": tid, "name": tm.get("name") or "Methodology",
                                        "input": tm.get("call_input") or {}})
                    declared.add(tid)
            all_tcs = explicit + synthesized
            if all_tcs:
                entry["tool_calls"] = [
                    {
                        "id": tc.get("id"),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": json.dumps(
                                tc.get("inputs", tc.get("input", {})) or {}
                            ),
                        },
                    }
                    for tc in all_tcs
                ]
            out.append(entry)
            for tm in tool_msgs:
                out.append({
                    "role": "tool",
                    "tool_call_id": tm["tool_call_id"],
                    "content": tm.get("content", ""),
                })
        else:
            i += 1
    return _ensure_user_after_system(out)


# The minimal wire keeps the user's request out of the messages (it lives in the
# Methodology system block) and starts a tool-results-only turn with an assistant "."
# stub. Z.AI rejects a payload whose first non-system message is not a user one
# (HTTP 400, code 1214 "The messages parameter is illegal"); the other OpenAI-compatible
# providers accept a leading user message as well, so one is always put there.
_CONTINUATION_USER = "(suite de la tâche en cours : résultats d'outils ci-dessous)"


def _ensure_user_after_system(out: list) -> list:
    if len(out) > 1 and out[1]["role"] != "user":
        out.insert(1, {"role": "user", "content": _CONTINUATION_USER})
    return out


def accumulate_tool_call_deltas(deltas: list, tool_buf: dict) -> None:
    for d in deltas or []:
        idx = d.get("index", 0)
        slot = tool_buf.setdefault(idx, {"id": None, "name": "", "args": ""})
        if d.get("id"):
            slot["id"] = d["id"]
        fn = d.get("function") or {}
        if fn.get("name"):
            slot["name"] += fn["name"]
        if fn.get("arguments"):
            slot["args"] += fn["arguments"]


def finalize_tool_calls(tool_buf: dict) -> list:
    out = []
    for idx in sorted(tool_buf):
        slot = tool_buf[idx]
        if not slot["name"]:
            continue
        tid = slot["id"] or f"or_{idx}"
        raw = slot["args"].strip()
        try:
            inp = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, ValueError) as e:
            out.append({
                "id": tid,
                "name": "_ToolArgsParseError",
                "input": {"_error": str(e), "_tool": slot["name"], "_raw": raw[:500]},
            })
            continue
        if not isinstance(inp, dict):
            inp = {"_value": inp}
        out.append({"id": tid, "name": slot["name"], "input": inp})
    return out
