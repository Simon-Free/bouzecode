# [desc] Forced side-calls that recover a missing Methodology / Snippet to augment a turn before exec. [/desc]
"""Out-of-band working-memory recovery via focused FORCED side-calls.

The agent loop, when a turn's batch is missing Methodology and/or fails to Snippet
the previous turn's Read/Skill results, recovers them BEFORE executing the batch:

  - recover_methodology(): forced Methodology, seeded with the previous Methodology
    + what this turn DID (tool calls, key arguments, the results it had just received).
    Prepended to the batch.
  - recover_snippets(): forced Snippet(s), seeded with the previous turn's Read/Skill
    results (already executed → content available). Appended.

The model's own reasoning is never copied into these user messages: measured 2026-09-29,
reasoning sent back as TEXT trips claude-opus-5's refusal classifier.

Each is a separate minimal call with tool_choice forced. The recovered calls join the
turn's own tool_calls and execute together — no in-wire bounce, no stash, no re-prompt,
so duplication/loops are structurally impossible.
"""
from __future__ import annotations


_METHODOLOGY_RECOVERY_SYSTEM = (
    "Tu maintiens la mémoire de travail (Methodology) d'un agent de code, entre des tours "
    "où presque tout son contexte est oublié. La Methodology est append-only : elle contient "
    "une todolist `[ ]`/`[x]` (tâches à faire / faites ce tour) plus les découvertes, décisions, "
    "signatures, chemins et résultats clés. On te donne la Methodology actuelle, les outils que "
    "l'agent vient d'appeler (avec leurs arguments) et les résultats qu'il venait de recevoir. "
    "Réponds UNIQUEMENT par un appel Methodology(content=...) qui consigne ce tour (coche/ajoute "
    "la todolist, note les nouveautés) — aucun texte, aucun autre outil."
)

_SNIPPET_RECOVERY_SYSTEM = (
    "Tu figes la mémoire de travail d'un agent. Pour CHAQUE résultat Read/Skill qu'il vient de "
    "recevoir : soit tu gardes ses régions utiles via Snippet(file_path=... (ou tool_id=...), "
    "ranges=[[début,fin]], label=...), soit tu le jettes via Snippet(discard=true, avec son "
    "file_path ou tool_id). Garde ce qui sert la tâche en cours ; jette le bruit (boilerplate, "
    "fichier exploré non pertinent, skill rechargeable). Réponds UNIQUEMENT par des appels "
    "Snippet — aucun texte, aucun autre outil."
)


def snippetable_results(messages: list) -> list[dict]:
    """Read/Skill/tool_id-snippetable results of the LAST assistant turn that has such
    calls (not necessarily the most recent turn), with file_path resolved. When recovery
    fires, that turn has already executed, so its tool results are present.

    Results below SNIPPET_MIN_LINES are excluded — they don't need snippet enforcement.
    """
    from ..tools.enforcement_hooks import _is_tool_id_snippetable
    from ..tools.skill.conservation import skill_conservee
    from .snippet_wire import SNIPPET_MIN_LINES

    def _snippetable(tc_name) -> bool:
        return tc_name in ("Read", "Skill") or _is_tool_id_snippetable(tc_name)

    idx = None
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.get("role") == "assistant" and any(
                _snippetable(tc.get("name")) for tc in (m.get("tool_calls") or [])):
            idx = i
            break
    if idx is None:
        return []
    calls = {tc["id"]: tc for tc in (messages[idx].get("tool_calls") or [])}
    out = []
    for m in messages[idx + 1:]:
        if m.get("role") == "assistant":
            break
        if m.get("role") == "tool" and _snippetable(m.get("name")):
            tcid = m.get("tool_call_id")
            content = m.get("content") or ""
            line_count = content.count("\n") + (1 if content else 0)
            if line_count < SNIPPET_MIN_LINES or skill_conservee(content):
                continue
            fp =((calls.get(tcid, {}) or {}).get("input") or {}).get("file_path", "")
            out.append({"tool_id": tcid, "name": m.get("name"), "file_path": fp,
                        "content": content})
    return out


def _ask_forced(tool_name: str, system: str, context_msg: str, config: dict,
                *, required: bool = False) -> list[dict]:
    """Focused side call: minimal system, only `tool_name` offered, tool_choice forced.
    Returns the list of `tool_name` calls the model emitted.

    Minimal on purpose: _depth=1 skips the depth-0 code profile, _context_state is dropped
    so dispatch adds no methodology system-blocks (the relevant state is in `context_msg`).
    `required` forces tool_choice="required" (≥1 call — for Snippet which may be several);
    otherwise tool_choice is pinned to the single function. Models that refuse a forced
    choice get "auto" instead (providers/backends/tool_choice_policy); the system prompt
    names the tool, and a reply without it simply yields no call."""
    from .providers import AssistantTurn
    from .stream_interceptor import get_streamer
    from ..core.tool_registry import get_tool_schemas

    schemas = [s for s in get_tool_schemas() if s["name"] == tool_name]
    side = dict(config)
    side["_depth"] = 1
    side["_context_state"] = None
    # Cost accepted: full context avoids a downstream re-Read that costs more.
    side["max_tokens"] = 2048
    side["_call_label"] = f"recover_{tool_name}"
    side["_tool_choice"] = "required" if required else {"type": "function",
                                                        "function": {"name": tool_name}}
    _stream = get_streamer()
    out: list[dict] = []
    for ev in _stream(model=config["model"], system=system,
                      messages=[{"role": "user", "content": context_msg}],
                      tool_schemas=schemas, config=side):
        if isinstance(ev, AssistantTurn):
            out = [tc for tc in (ev.tool_calls or []) if tc.get("name") == tool_name]
    return out


def _resume_appel(tc: dict) -> str:
    """« Edit app.js », « Bash pytest -q tests » : de quoi retrouver ce que le tour a lancé."""
    import os
    inp = tc.get("input") or tc.get("inputs") or {}
    cible = inp.get("file_path") or inp.get("path") or ""
    if cible:
        return f"{tc['name']} {os.path.basename(str(cible).rstrip('/')) or cible}"
    commande = str(inp.get("command") or inp.get("pattern") or "").strip().split("\n")[0]
    return f"{tc['name']} {commande[:40]}".rstrip()


def mechanical_methodology(tool_calls: list[dict] | None) -> dict:
    """Rattrapage SANS appel LLM (`methodology_recovery = "mecanique"`) : une ligne écrite par
    le harnais. Le tampon `### T<n>` est posé par l'outil Methodology lui-même."""
    outils = ", ".join(_resume_appel(tc) for tc in tool_calls or []
                       if tc.get("name") not in ("Methodology", "Snippet"))
    return {"id": "", "name": "Methodology", "input": {
        "content": f"(note non écrite par le modèle) — outils : {outils or 'aucun'}"}}


def _received_results(messages: list, max_chars: int = 1500) -> list[str]:
    """Tool results the current turn had just received: the `tool` messages right before
    its assistant message (the last one). Each is capped — the note keeps findings, not dumps."""
    received = []
    for m in reversed(messages[:-1]):
        if m.get("role") != "tool":
            break
        received.append(f"─ {m.get('name') or 'outil'} :\n{str(m.get('content') or '')[:max_chars]}")
    return received[::-1]


def recover_methodology(state, config: dict, ctx, tool_calls: list[dict] | None = None) -> dict | None:
    """Forced Methodology recovery: seeded with the previous Methodology + this turn's tool
    calls (key arguments) + the results it had just received, tool_choice pinned to
    Methodology. Returns the Methodology tool_call or None.

    `methodology_recovery = "mecanique"` : pas d'appel LLM, une ligne mécanique (outils du tour).
    Même déclencheur dans les deux cas : un tour sans réflexion (`ctx.thinking_parts`, qui sert
    de déclencheur sans jamais être envoyé) ou sans outil n'a rien à rattraper."""
    import json
    from ..context_manager.state import METHODOLOGY_NOTE

    work_calls = [tc for tc in tool_calls or [] if tc.get("name") not in ("Methodology", "Snippet")]
    if not "".join(getattr(ctx, "thinking_parts", []) or []).strip() or not work_calls:
        return None
    if config.get("methodology_recovery") == "mecanique":
        return mechanical_methodology(tool_calls)
    cs = config.get("_context_state")
    prev = (cs.notes.get(METHODOLOGY_NOTE, "") if cs and getattr(cs, "notes", None) else "") or ""

    parts = []
    if prev.strip():
        parts.append(f"Methodology actuelle (état de ta mémoire) :\n{prev.strip()}")
    parts.append("Outils appelés ce tour :\n" + "\n".join(
        f"- {tc['name']} {json.dumps(tc.get('input') or {}, ensure_ascii=False)[:300]}"
        for tc in work_calls))
    received = _received_results(getattr(state, "messages", None) or [])
    if received:
        parts.append("Résultats reçus juste avant ce tour :\n" + "\n".join(received))
    calls = _ask_forced("Methodology", _METHODOLOGY_RECOVERY_SYSTEM, "\n\n".join(parts), config)
    return calls[0] if calls else None


def recover_snippets(snip_results: list[dict], ctx, config: dict, state=None) -> list[dict]:
    """Forced Snippet recovery with FULL context: user prompt, methodology and complete
    tool_result contents (no truncation). `ctx` is kept for the call signature only.

    Cost accepted: full context avoids a downstream re-Read that costs more."""
    if not snip_results:
        return []
    from ..context_manager.state import METHODOLOGY_NOTE

    parts = []
    # (a) Initial user prompt — grounds the decision in the task
    if state and getattr(state, "messages", None):
        user_msgs = [m for m in state.messages if m.get("role") == "user"]
        if user_msgs:
            parts.append(f"Prompt utilisateur initial :\n{user_msgs[0].get('content', '')}")
    # (b) Full methodology note — current working memory
    cs = config.get("_context_state")
    prev_meth = (cs.notes.get(METHODOLOGY_NOTE, "") if cs and getattr(cs, "notes", None) else "")
    if prev_meth.strip():
        parts.append(f"Methodology actuelle :\n{prev_meth.strip()}")
    # (c) Complete tool_result contents — NO truncation
    parts.append("Résultats Read/Skill reçus au tour précédent — fige (Snippet) ou jette (discard) CHACUN :")
    for r in snip_results:
        head = f"─ tool_id={r['tool_id']} [{r['name']}]"
        if r.get("file_path"):
            head += f" file_path={r['file_path']}"
        parts.append(f"{head} :\n{r.get('content') or ''}")
    return _ask_forced("Snippet", _SNIPPET_RECOVERY_SYSTEM, "\n\n".join(parts), config, required=True)
