# [desc] Minimal-wire pipeline for methodology-centric architecture: keep only the last asst+tools batch, user msgs, and Write/Edit acks. Prior assistant messages dropped entirely. [/desc]
"""Build the on-wire payload under the methodology-centric architecture.

The contract communicated to the model: every persistent fact lives in the
methodology note (cached, in <working_notes> at the head of the first user
message). At each turn the wire contains only:
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

import json

# Consigne du harnais, posée à part du résultat (clé HARNESS_NOTE_KEY) : dispatch la regroupe
# dans le bloc <harness_notes> qui suit les tool_results. Écrite DANS un tool_result, elle
# faisait refuser claude-opus-5-5 (content_filter du gateway, rejeux du 2026-10-07).
_DESTRUCTION_NOTICE = (
    "The tool_results above are destroyed at the next turn unless you snippet them "
    "or stash a note with Methodology."
)

# Un message user posé PENDANT le tour, juste après les résultats d'un lot (courrier relevé à
# la frontière de tour, relance du harnais) : le lot reste vivant. Sans cette marque, le fil
# lisait ce message comme la FIN du lot et n'envoyait que lui (keep=0) — mesuré à l'essai du
# 2026-09-25 : l'enfant 40ea29e4 a perdu les 3 résultats de son tour 35 en recevant le message
# de son parent, la racine 6bafe9cd les 5 de son tour 72 avec une précision relayée.
SUITE_DU_LOT = "_suite_du_lot"


def message_du_lot(texte: str) -> dict:
    """Le message user qui suit les résultats du lot en cours, sans les retirer du fil."""
    return {"role": "user", "content": texte, SUITE_DU_LOT: True}


def _last_asst_with_tools_idx(messages: list[dict]) -> int:
    """Index of the asst-with-tool_calls whose batch is still 'live' for this
    LLM call. A batch is live only when it sits at the tail of the message
    list followed by nothing or only its own tool_results. If a later user
    msg or no-tools asst has arrived, the batch is finished and gets pruned
    like any other prior batch.
    """
    j = len(messages) - 1
    # Skip trailing overflow-cut sequences: an overflow cuts a turn mid-analysis
    # with no tool call, appending assistant(_overflow_cut)+user(nudge) AFTER the
    # previous batch's tool_results. That batch is unfinished — the model was cut
    # while reasoning about it — so keep it live (don't let the cut orphan it),
    # else the freshly-fetched material (e.g. a BR) is dropped and re-fetched,
    # re-triggering overflow (loop). Loop to handle consecutive overflows.
    # `_empty_completion` (2026-08-26) is skipped for the exact same reason as
    # `_overflow_cut`: the model returned NOTHING (no text, no thinking, no tool call),
    # so the batch it was supposed to act on is still unfinished. Without this skip the
    # trailing assistant(empty)+user(nudge) pair made this function return -1, and
    # `build_minimal_payload` then shipped `[user_msg]` ALONE — the live batch's
    # tool_results were RAZED (that is the keep=0 / api_input_tokens=566 seen in
    # turns.jsonl), producing a degenerate request that yielded another empty reply:
    # a permanent loop at ~0.2s/turn. Keeping the batch live is the context FLOOR.
    while (
        j >= 1
        and messages[j].get("role") == "user"
        and messages[j - 1].get("role") == "assistant"
        and (messages[j - 1].get("_overflow_cut")
             or messages[j - 1].get("_empty_completion"))
    ):
        j -= 2
    j = _avant_la_suite_du_lot(messages, j)
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


def _avant_la_suite_du_lot(messages: list[dict], j: int) -> int:
    """Remonte les messages posés pendant le tour (`SUITE_DU_LOT`) puis les résultats d'outils :
    l'index qui reste est ce qui les précède (le lot, s'il y en a un)."""
    while j >= 0 and messages[j].get("role") == "user" and messages[j].get(SUITE_DU_LOT):
        j -= 1
    while j >= 0 and messages[j].get("role") == "tool":
        j -= 1
    return j


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


def _build_tool_input_index(messages: list[dict]) -> dict[str, dict]:
    """Map tool_call_id -> input dict across the full message history."""
    index: dict[str, dict] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            tid = tc.get("id")
            if tid:
                index[tid] = tc.get("inputs", tc.get("input", {})) or {}
    return index


def _tool_call_recall(name: str, input_dict: dict) -> str:
    """Compact one-line reminder of the tool_call that produced a result.

    The live-batch assistant message (with its tool_use XML) is dropped from the
    wire, so a surviving tool_result would otherwise lose all trace of the
    command/input that produced it. Prefix it with this recall so the model
    keeps the context of what it ran.
    """
    import json as _json
    name = name or "tool"
    if name in ("Methodology", "Snippet", "ResetContext"):
        # Jamais leurs arguments : la note est déjà dans le bloc METHODOLOGY. Recopier côté
        # utilisateur le texte que le modèle vient d'écrire faisait refuser claude-opus-5
        # par le filtre du gateway en milieu de conversation (incident Focus 2026-09-29).
        return f"[↩ {name}]\n"
    if name in ("Write", "Edit") and isinstance(input_dict, dict) and input_dict.get("file_path"):
        # Jamais le contenu tronqué : il faisait croire à un fichier partiel. Le résultat,
        # juste en dessous, porte l'aperçu numéroté de ce qui a réellement été écrit.
        return f"[↩ {name}: {input_dict['file_path']}{_taille_ecrite(name, input_dict)}]\n"
    if isinstance(input_dict, dict) and input_dict.get("command"):
        compact = str(input_dict["command"])
    else:
        try:
            compact = _json.dumps(input_dict, ensure_ascii=False)
        except (TypeError, ValueError):
            compact = str(input_dict)
    compact = compact.replace("\n", " ")
    if len(compact) > 200:
        compact = compact[:200] + "…"
    return f"[↩ {name}: {compact}]\n"


def _taille_ecrite(name: str, input_dict: dict) -> str:
    texte = input_dict.get("content" if name == "Write" else "new_string") or ""
    if not texte:
        return ""
    lignes = texte.count("\n") + (0 if texte.endswith("\n") else 1)
    return f" ({lignes} lignes écrites)" if name == "Write" else f" ({lignes} lignes remplacées)"


def _build_file_path_index(messages: list[dict]) -> dict[str, str]:
    """Map tool_call_id -> file_path for Read/Skill/Edit/Write calls (used for file snippet wrapping)."""
    index: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            name = tc.get("name")
            if name in ("Read", "Skill", "Edit", "Write"):
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


def _compact_model_envelope(content: str) -> str | None:
    """If a tool_result is a PBI model envelope (the full model.bim / pbit bytes
    plus a human 'summary'), return just the summary for the wire — else None.

    pbi_* write tools (add_measure, add_table, add_relationship, edit_*, …) echo
    the ENTIRE growing model.bim on every call. The model is persisted in the
    artifacts store at execution time, so the model never needs to reach the LLM;
    re-sending it was the dominant fresh-token cost (e.g. 21 add_measure calls in
    one turn each re-emitting the whole ~25 KB model). The summary keeps the
    actionable feedback (what changed + table/measure/relation counts)."""
    if not content or '"summary"' not in content:
        return None
    if '"pbi_model"' not in content and '"pbit_files"' not in content:
        return None
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or "summary" not in data:
        return None
    if "pbi_model" not in data and "pbit_files" not in data:
        return None
    return data["summary"]


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


def _latest_user_only(messages: list[dict], latest_user: int,
                      interrupted_content: str | None) -> list[dict]:
    """Wire without a live batch: the latest user message alone (Ctrl+C prefix included)."""
    if latest_user < 0:
        return []
    user_msg = dict(messages[latest_user])
    if interrupted_content:
        user_msg["content"] = (
            _INTERRUPTED_BANNER + interrupted_content
            + "\n\n---\n\n" + (user_msg.get("content", "") or "")
        )
    return [user_msg]


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
        return _latest_user_only(messages, latest_user, interrupted_content)

    # Drop the live-batch assistant message itself (its prose + tool_use XML are
    # redundant — methodology + tool_results convey everything). Keep only what
    # follows it (tool_results, the enforcement/next user msg). The Ctrl+C case is
    # handled separately via interrupted_content, which prefixes the user message.
    # Snippetable results get numbered lines; their "A SNIPPETER" instruction rides apart
    # (HARNESS_NOTE_KEY), for the <harness_notes> block that dispatch places after them:
    # - tool_id-keyed (FindCode, Tree, LoadProjectConfig): id: tool_id=...
    # - file-keyed (Read, Skill, Edit, Write): id: file=<path>
    # The first non-snippetable result carries the destruction notice instead.
    from .snippet_wire import (
        is_snippetable_tool_id, mark_snippetable, HARNESS_NOTE_KEY,
        is_file_snippetable, mark_file_snippetable, mark_write_snippetable,
        SNIPPET_MIN_LINES, _line_count,
    )

    result: list[dict] = []
    banner_injected = False
    name_index = _build_tool_name_index(messages)
    file_path_index = _build_file_path_index(messages)
    input_index = _build_tool_input_index(messages)
    for i in range(last_batch + 1, len(messages)):
        msg = messages[i]
        if msg.get("_interrupted"):
            continue  # Skip _interrupted from wire (injected as prefix instead)
        if msg.get("role") == "tool":
            tool_id = msg.get("tool_call_id")
            tool_name = name_index.get(tool_id)
            # Ni l'appel Methodology ni son résultat : la note est déjà dans le fil (<working_notes>,
            # bloc METHODOLOGY). Redéclaré en argument d'outil, il faisait refuser claude-opus-5-5
            # (content_filter du gateway, session bb991b7c du 2026-10-07 : 8/8 refus avec, 0/8 sans).
            if tool_name == "Methodology":
                continue
            content = msg.get("content", "") or ""
            compacted_model = _compact_model_envelope(content)
            # PBI model envelopes carry the full model.bim — drop it to the summary
            # on the wire (the model is persisted in artifacts at execution time).
            if compacted_model is not None:
                cleaned = dict(msg)
                cleaned["content"] = compacted_model
                result.append(cleaned)
            # For snippetable tools, only wrap if content meets line threshold;
            # small results fall through to the normal banner/passthrough path.
            elif is_snippetable_tool_id(tool_name) and _line_count(content) >= SNIPPET_MIN_LINES:
                cleaned = dict(msg)
                cleaned["content"], cleaned[HARNESS_NOTE_KEY] = mark_snippetable(content, tool_id)
                result.append(cleaned)
            elif is_file_snippetable(tool_name) and file_path_index.get(tool_id) and _line_count(content) >= SNIPPET_MIN_LINES:
                cleaned = dict(msg)
                mark = mark_write_snippetable if tool_name in ("Write", "Edit") \
                    else mark_file_snippetable
                cleaned["content"], cleaned[HARNESS_NOTE_KEY] = mark(
                    content, file_path_index[tool_id], tool_id)
                result.append(cleaned)
            elif not banner_injected:
                cleaned = dict(msg)
                recall = _tool_call_recall(tool_name, input_index.get(tool_id, {}))
                cleaned["content"] = recall + content
                cleaned[HARNESS_NOTE_KEY] = _DESTRUCTION_NOTICE
                result.append(cleaned)
                banner_injected = True
            else:
                cleaned = dict(msg)
                recall = _tool_call_recall(tool_name, input_index.get(tool_id, {}))
                cleaned["content"] = recall + content
                result.append(cleaned)
            # Le message assistant du lot est retiré du fil : les convertisseurs à outils natifs
            # redéclarent ses appels depuis les résultats. Sans les VRAIS arguments, ils les
            # redéclaraient avec `{}`, et le modèle recopiait ce lot vide (claude-opus-5-5 sur le
            # gateway, 2026-10-05 : 5 lots vides sur 22 rejeux, 0 sur 12 avec les arguments).
            result[-1]["call_input"] = input_index.get(tool_id, {})
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
    # note), so when the batch's tool_results would lead, prepend a
    # minimal assistant stub. In the enforcement pattern a trailing user message
    # already provides a valid leading role, so no stub is added there.
    # Lot réduit à Methodology seul : rien n'en reste, le fil retombe sur la demande.
    if not result:
        return _latest_user_only(messages, latest_user, interrupted_content)
    if result[0].get("role") == "tool":
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
    """Methodology-centric pipeline: strip thinking, prune to minimal wire payload, then put
    the user's current request first (`demande_en_cours`)."""
    from .demande_en_cours import demande_en_cours, mettre_la_demande_en_tete
    result = list(state.messages)
    result = _strip_thinking_from_messages(result)
    result = build_minimal_payload(result)
    return mettre_la_demande_en_tete(result, demande_en_cours(state))
