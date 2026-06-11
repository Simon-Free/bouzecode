# [desc] Routes an LLM turn to the Anthropic socle or OpenRouter backend, assembling system blocks, methodology and native tools. [/desc]
from __future__ import annotations
import os
from typing import Generator

from ..registry import (
    resolve_provider, model_uses_native_tools,
    get_api_key, get_openrouter_key, PROVIDERS,
)
from .anthropic_stream import stream_anthropic


# "Taxe Methodology" (A/B 2026-06-10): deepseek omitted Methodology on ~25% of
# native turns, costing one forced recovery side-call each time. Repeating a
# hard rule at the VERY END of the native system prompt (recency beats burial)
# measured 25%->11.5% omissions and 6/6 ticket successes vs 5/6 baseline, token
# cost neutral. Default ON for native models; BOUZECODE_METH_PROMPT_VARIANT=off
# disables (for re-benching the baseline).
_NATIVE_METH_RULE = (
    "RÈGLE FINALE NON NÉGOCIABLE (mode tool-calling natif) : CHAQUE message "
    "assistant qui contient des tool_calls DOIT inclure un appel "
    "Methodology(content=...) DANS le même batch, en PREMIER. Un batch sans "
    "Methodology = ta mémoire de travail de ce tour est PERDUE et un appel de "
    "rattrapage coûteux est déclenché. Même un tour de pure exploration note ses "
    "découvertes : todolist `[ ]`/`[x]` mise à jour + faits nouveaux, une ligne "
    "minimum. CLÔTURE : quand la tâche est entièrement terminée (ou ta réponse "
    "finale prête), appelle FinalAnswer(answer=...) dans le même batch que ta "
    "dernière Methodology — c'est LE signal de fin de session. Ta clôture est "
    "VALIDÉE contre ta Methodology : une todolist avec des `[ ]` non justifiés "
    "= clôture refusée. N'itère pas après le succès : tâche validée = "
    "FinalAnswer immédiat."
)

_SEED_METHODOLOGY_PLACEHOLDER = (
    "[METHODOLOGY — your persistent working memory across turns]\n"
    "**Note vide — à remplir DÈS CE TOUR.**\n\n"
    "Utilisez l'outil Methodology pour sauver vos conclusions :\n"
    "```xml\n"
    '<tool_use name="Methodology" id="m1">'
    '<param name="content">votre note ici</param>'
    "</tool_use>\n"
    "```\n\n"
    "Rappel : chaque message assistant DOIT contenir ≥1 tool_call. "
    "Methodology en premier, puis vos actions."
)


def _inject_into_last_user_message(messages: list, extra: str) -> None:
    """Prepend per-iteration content (audit note, working memory) to the last user message."""
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            messages[i] = dict(messages[i])
            content = messages[i]["content"]
            if isinstance(content, list):
                messages[i]["content"] = [{"type": "text", "text": extra}] + content
            else:
                messages[i]["content"] = extra + "\n\n" + content
            return


def _require_key(provider_name: str, config: dict) -> str:
    """Resolve and validate the API key before any streaming begins, so a missing
    key raises immediately (before the SystemPayload is yielded)."""
    if provider_name == "openrouter":
        key = get_openrouter_key(config)
        if not key:
            raise RuntimeError(
                "\n\n"
                "  No OpenRouter API key found.\n\n"
                "  Add OPENROUTER_KEY=sk-or-... to your .env file\n"
                "  (in the bouzecode repo root), or set it as an\n"
                "  environment variable before launching bouzecode.\n"
            )
        return key
    key = get_api_key(config)
    if not key:
        raise RuntimeError(
            "\n\n"
            "  No Anthropic API key found.\n\n"
            "  Add ANTHROPIC_API_KEY=sk-ant-... to your .env file\n"
            "  (in the bouzecode repo root), or set it as an\n"
            "  environment variable before launching bouzecode.\n"
        )
    return key


def _resolve_cache_control(base_url: str | None) -> dict:
    """TTL "1h" coûte 2× à l'écriture (vs 1,25× en 5 min) mais nos sessions font
    des dizaines de lectures par fenêtre. Toujours actif sur l'API officielle ;
    ailleurs (socle) derrière BOUZECODE_CACHE_TTL_1H=1 (défaut off)."""
    is_official_anthropic = base_url is None or "api.anthropic.com" in base_url
    if is_official_anthropic or os.environ.get("BOUZECODE_CACHE_TTL_1H", "0") == "1":
        return {"type": "ephemeral", "ttl": "1h"}
    return {"type": "ephemeral"}


def stream(
    model: str,
    system: str,
    messages: list,
    tool_schemas: list,
    config: dict,
) -> Generator:
    provider_name, model_name = resolve_provider(model)
    # Validate the key up front: a missing key must raise before the first yield.
    api_key = _require_key(provider_name, config)
    native = model_uses_native_tools(model, config)

    from ....xml_tool_protocol import build_tool_docs
    from ....core.context import build_system_prompt_parts
    from ....context_manager import build_verbatim_audit_note
    from ....context_manager.state import METHODOLOGY_NOTE
    from ....context_manager.methodology import build_methodology_system_blocks

    if system:
        stable_prefix, volatile = system, ""
    else:
        stable_prefix, volatile = build_system_prompt_parts(config)
    # The top-level agent (depth 0) is the code-development agent: append the
    # `default` profile's system_prompt_extra (TDD, tests, discovery, interdicts)
    # on top of the shared noyau. Sub-agents (depth > 0) inherit only the noyau and
    # apply their own profile, so this never leaks into them.
    if config.get("_depth", 0) == 0:
        from ....core.context import get_agent_profile_extra
        classification = config.get("_task_classification_result", "default")
        profile_extra = get_agent_profile_extra(classification)
        if profile_extra:
            stable_prefix = f"{stable_prefix.rstrip()}\n\n{profile_extra}"
    # In native mode tools are sent via the API `tools` param, so the XML tool docs
    # block is redundant — keep it empty to avoid duplicating the schemas.
    tool_docs = "" if native else build_tool_docs(tool_schemas or [])
    native_tools = None
    if native:
        from .openrouter_native import tool_schemas_to_openai
        native_tools = tool_schemas_to_openai(tool_schemas or [])

    audit_note = build_verbatim_audit_note(messages)
    context_state = config.get("_context_state")
    methodology_text = ""
    notes_block = ""
    if context_state and context_state.notes:
        methodology_text = context_state.notes.get(METHODOLOGY_NOTE, "") or ""
        other_notes = {n: c for n, c in context_state.notes.items() if n != METHODOLOGY_NOTE}
        if other_notes:
            notes_block = "[Your working memory notes]\n" + "\n\n".join(
                f"## {name}\n{content}" for name, content in other_notes.items()
            ) + "\n[/Notes]"
    per_iter = "\n\n".join(filter(None, [audit_note, notes_block]))
    if per_iter:
        messages = list(messages)
        _inject_into_last_user_message(messages, per_iter)

    base_url = os.environ.get("ANTHROPIC_BASE_URL") or PROVIDERS["anthropic"].get("base_url")
    cache_control = _resolve_cache_control(base_url)
    snapshot = getattr(context_state, "_methodology_cache_snapshot", "") if context_state else ""
    meth_blocks, meth_delta = build_methodology_system_blocks(
        methodology_text, snapshot, cache_control,
    )
    # Seed placeholder: when methodology is empty, inject a transitional hint
    # to reduce first-turn tool-call omission (82% when meth=0).
    seed_placeholder_blocks: list[dict] = []
    if not meth_blocks and os.environ.get("BOUZECODE_SEED_METHODOLOGY", "1") != "0":
        seed_placeholder_blocks = [
            {"type": "text", "text": _SEED_METHODOLOGY_PLACEHOLDER}
        ]
    delta_block = (
        [{"type": "text", "text": meth_delta, "cache_control": cache_control}]
        if meth_delta else []
    )
    system_blocks = [
        {"type": "text", "text": stable_prefix, "cache_control": cache_control},
        {"type": "text", "text": tool_docs, "cache_control": cache_control},
        *meth_blocks,
        *seed_placeholder_blocks,
        *delta_block,
        {"type": "text", "text": volatile},
    ]
    if native and os.environ.get("BOUZECODE_METH_PROMPT_VARIANT", "A") != "off":
        system_blocks.append({"type": "text", "text": _NATIVE_METH_RULE})
    from ..types import SystemPayload
    yield SystemPayload(system_blocks, tools=native_tools)

    if provider_name == "openrouter":
        from .openrouter_stream import stream_openrouter
        yield from stream_openrouter(
            api_key, model_name, system_blocks, messages, tool_schemas, config,
        )
    else:
        yield from stream_anthropic(
            api_key, model_name, system_blocks, messages, tool_schemas, config,
            base_url=base_url, cache_last=False,
        )
    if context_state and methodology_text:
        context_state._methodology_cache_snapshot = methodology_text
