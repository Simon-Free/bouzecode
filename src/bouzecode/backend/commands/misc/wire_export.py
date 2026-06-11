# [desc] Render the exact per-turn LLM wire (system blocks + messages) to markdown for debugging. [/desc]
"""Export the verbatim per-turn LLM payload to markdown.

Source: ``~/.bouzecode/debug_payloads/<session_id>/turns.jsonl`` written by
``payload_dump.dump_turn_payload`` — the system_blocks + messages actually
sent to the model each turn (after thinking-strip + minimal-wire pruning).

Note on fidelity: the dumped ``messages`` are captured *before* dispatch injects
the per-iteration working-memory/audit note into the last user message. Those
notes are surfaced separately here (from ``gc_state.notes``); the methodology
system block IS captured verbatim.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

_BLOCK_LABELS = [
    "stable_prefix (system prompt)", "tool_docs (XML auto)",
    "methodology", "methodology_delta", "volatile",
]


def _turns_path(session_id: str, payloads_dir: Path | None) -> Path:
    if payloads_dir is not None:
        return Path(payloads_dir) / "turns.jsonl"
    from ...agent.payload_dump import _payload_dir
    return _payload_dir(session_id) / "turns.jsonl"


def _load_turns(path: Path) -> dict:
    """Return {turn_number: record}, keeping the LAST record per turn.

    Each turn writes a pre-stream record (request only) then an enriched record
    (request + system_blocks + token_counts + response); on interruption the
    enriched record is written by the cancel handler. The richest record is
    always written last, so last-wins gives the fullest view."""
    turns: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        turns[rec.get("turn")] = rec
    return turns


def _render_system_blocks(blocks) -> str:
    if not blocks:
        return "_(system_blocks non capturés pour ce tour — stream interrompu ?)_"
    out = []
    for i, b in enumerate(blocks):
        text = b.get("text", "") if isinstance(b, dict) else str(b)
        cc = b.get("cache_control") if isinstance(b, dict) else None
        label = _BLOCK_LABELS[i] if i < len(_BLOCK_LABELS) else f"block {i}"
        cc_note = f" · cache_control={cc}" if cc else ""
        out.append(f"##### system[{i}] — {label}{cc_note}\n\n```\n{text}\n```")
    return "\n\n".join(out)


def _render_content(content) -> str:
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                parts.append(b.get("text") or b.get("content") or json.dumps(b, ensure_ascii=False))
            else:
                parts.append(str(b))
        return "\n".join(parts)
    return str(content or "")


def _render_messages(messages) -> str:
    out = []
    for m in messages or []:
        role = m.get("role", "?")
        if role == "tool":
            name = m.get("name", "tool")
            out.append(
                f"**[tool_result]** `{name}` (id={m.get('tool_call_id', '')})\n\n"
                f"```\n{_render_content(m.get('content'))}\n```"
            )
            continue
        body = _render_content(m.get("content"))
        out.append(f"**[{role}]**\n\n{body}" if body.strip() else f"**[{role}]** _(vide)_")
        for tc in m.get("tool_calls") or []:
            inp = json.dumps(tc.get("input", {}), ensure_ascii=False, indent=2)
            out.append(
                f"  - 🔧 **tool_call** `{tc.get('name')}` (id={tc.get('id')})\n\n"
                f"```json\n{inp}\n```"
            )
    return "\n\n".join(out)


def _render_response(resp: dict | None) -> str:
    if not resp:
        return "_(réponse non capturée pour ce tour)_"
    flags = []
    if resp.get("interrupted"):
        flags.append("⚠️ INTERROMPU (Ctrl+C) — réponse partielle")
    if resp.get("partial"):
        flags.append("réponse partielle (stream incomplet)")
    if resp.get("thinking_overflow"):
        flags.append("thinking overflow")
    if resp.get("stop_reason"):
        flags.append(f"stop_reason={resp['stop_reason']}")
    out = []
    if flags:
        out.append("> " + " · ".join(flags))
    thinking = resp.get("thinking") or ""
    if thinking.strip():
        out.append(f"**[thinking]**\n\n```\n{thinking}\n```")
    text = resp.get("text") or ""
    if text.strip():
        out.append(f"**[text]**\n\n{text}")
    for tc in resp.get("tool_calls") or []:
        inp = json.dumps(tc.get("input", {}), ensure_ascii=False, indent=2)
        out.append(
            f"  - 🔧 **tool_call** `{tc.get('name')}` (id={tc.get('id')})\n\n"
            f"```json\n{inp}\n```"
        )
    if not out:
        return "_(aucune sortie — ni texte, ni thinking, ni tool_call)_"
    return "\n\n".join(out)


def _render_tools(tools) -> str:
    """Render the native JSON `tools` param actually sent to the model.

    Native function-calling sends tool defs via the API `tools` param (not the
    system prompt), so without this section the export looks like the model got
    no tool docs at all.
    """
    if not tools:
        return "_(pas de `tools` JSON — modèle en protocole XML, voir system[tool_docs])_"
    import json as _json
    names = ", ".join(t.get("function", {}).get("name", "?") for t in tools)
    full = _json.dumps(tools, ensure_ascii=False, indent=2)
    return (
        f"#### TOOLS (param API `tools` — ce que voit RÉELLEMENT le modèle en JSON)\n\n"
        f"_{len(tools)} outils : {names}_\n\n```json\n{full}\n```"
    )


def _render_turn(rec: dict) -> str:
    n = rec.get("turn")
    tc = rec.get("token_counts") or {}
    tok = ""
    if tc:
        tok = (f"\n_tokens: in={tc.get('in_tokens')} out={tc.get('out_tokens')} "
               f"cache_read={tc.get('cache_read_tokens')} cache_write={tc.get('cache_creation_tokens')}_")
    notes = (rec.get("gc_state") or {}).get("notes") or {}
    note_keys = ", ".join(notes.keys()) if notes else "∅"
    return (
        f"## TURN {n}{tok}\n\n"
        f"_working-memory notes (injectées dans le dernier user msg sur le wire) : {note_keys}_\n\n"
        f"### REQUEST {n}\n\n"
        f"#### SYSTEM (ce que voit le modèle)\n\n"
        f"{_render_system_blocks(rec.get('system_blocks'))}\n\n"
        f"{_render_tools(rec.get('tools'))}\n\n"
        f"#### MESSAGES (wire)\n\n{_render_messages(rec.get('messages'))}\n\n"
        f"### RESPONSE {n}\n\n"
        f"{_render_response(rec.get('response'))}"
    )


def export_wire(session_id: str, turn: int | None = None,
                out_path=None, payloads_dir: Path | None = None):
    """Write the per-turn wire to markdown.

    Returns (Path, n_turns) on success, or (None, reason) on failure.
    """
    src = _turns_path(session_id, payloads_dir)
    if not src.exists():
        return None, f"aucun dump trouvé ({src})"
    turns = _load_turns(src)
    if not turns:
        return None, f"dump vide ({src})"

    if turn is not None:
        if turn not in turns:
            return None, f"tour {turn} introuvable (dispo : {sorted(turns)})"
        selected = [turns[turn]]
    else:
        selected = [turns[t] for t in sorted(turns)]

    header = (
        f"# Wire LLM — session {session_id}\n\n"
        f"_{len(selected)} tour(s) · généré le {datetime.now():%Y-%m-%d %H:%M:%S} · source {src}_\n\n"
    )
    body = "\n\n---\n\n".join(_render_turn(r) for r in selected)

    if out_path is None:
        suffix = f"turn{turn}" if turn is not None else "all"
        out_path = src.parent / f"wire_{suffix}.md"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(header + body, encoding="utf-8")
    return out_path, len(selected)
