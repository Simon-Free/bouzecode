# [desc] Routes an LLM turn to the Anthropic gateway or OpenRouter backend, assembling system blocks, methodology and native tools. [/desc]
from __future__ import annotations
import os
from typing import Generator

from ..registry import (
    resolve_provider, model_uses_native_tools,
    get_api_key, get_openrouter_key, get_gateway_preprod_key, PROVIDERS, check_provider_allowed,
)
from .anthropic_stream import stream_anthropic
from .encapsulation import avec_la_note, avec_les_notes_du_harnais, parties_de_la_note
from .prompt_echo import drop_prompt_echo
from .role_leak import cut_at_role_leak


# "Taxe Methodology" (A/B 2026-06-10): deepseek omitted Methodology on ~25% of
# native turns, costing one forced recovery side-call each time. Repeating a
# hard rule at the VERY END of the native system prompt (recency beats burial)
# measured 25%->11.5% omissions and 6/6 ticket successes vs 5/6 baseline, token
# cost neutral. Default ON for native models; BOUZECODE_METH_PROMPT_VARIANT=off
# disables (for re-benching the baseline).
#
# 2026-09-24 (audit du prompt) : réduit à une ligne. Le détail (Methodology en premier,
# clôture validée contre la note) est dit UNE fois dans le noyau ; ici ne reste que le
# rappel en position de récence, qui est ce que l'A/B a mesuré.
_NATIVE_METH_RULE = (
    "RAPPEL : chaque lot commence par Methodology ; la tâche finie → FinalAnswer dans le "
    "même lot que la dernière Methodology, todolist entièrement cochée."
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

# Same hint, without the XML example: in native mode the model calls Methodology
# through the API, and showing it an XML call on the very first turn would teach the
# protocol we just stopped using.
_SEED_METHODOLOGY_PLACEHOLDER_NATIVE = (
    "[METHODOLOGY — your persistent working memory across turns]\n"
    "**Note vide — à remplir DÈS CE TOUR.**\n\n"
    "Appelez l'outil Methodology avec votre note dans le paramètre `content` "
    "pour sauver vos conclusions.\n\n"
    "Rappel : chaque message assistant DOIT contenir ≥1 tool_call. "
    "Methodology en premier, puis vos actions."
)


def _regle_finale(provider_name: str) -> bool:
    """Règle finale en fin de system. A/B DeepSeek du 24/09
    (docs/reduction_tokens/correctifs.md §3) : sans elle, oublis de Methodology 15,4 % → 5,8 %,
    réussite 6/6 dans les deux bras, −19 % de tours. Retirée sur OpenRouter ; gardée ailleurs
    (Anthropic natif, gateway), où rien n'a été mesuré. BOUZECODE_METH_PROMPT_VARIANT=A la force,
    =off la retire partout."""
    variante = os.environ.get("BOUZECODE_METH_PROMPT_VARIANT", "")
    return variante == "A" or (variante != "off" and provider_name != "openrouter")


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
    if provider_name == "gateway_preprod":
        key = get_gateway_preprod_key(config)
        if not key:
            raise RuntimeError(
                "\n\n"
                "  No internal LLM gateway preprod key found.\n\n"
                "  Set the OPENAI_API_KEY_PP environment variable\n"
                "  before launching bouzecode.\n"
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
    ailleurs (gateway) derrière BOUZECODE_CACHE_TTL_1H=1 (défaut off)."""
    from bouzecode.backend.agent.providers.llm_proxy import is_llm_proxy

    # Le proxy LLM du portail relaie le gateway : même politique que lui (ttl 5 min par
    # défaut), même si son URL contenait un jour "api.anthropic.com".
    is_official_anthropic = not is_llm_proxy(base_url) and (
        base_url is None or "api.anthropic.com" in base_url)
    if is_official_anthropic or os.environ.get("BOUZECODE_CACHE_TTL_1H", "0") == "1":
        return {"type": "ephemeral", "ttl": "1h"}
    return {"type": "ephemeral"}


def provider_base_url(provider_name: str) -> str | None:
    """L'URL que vise CE fournisseur. La politique de cache se décide sur le point d'accès qui
    sert la requête : lue sur ANTHROPIC_BASE_URL pour tous, une session gateway_preprod sans cette
    variable passait pour l'API officielle et partait en ttl 1h — que le gateway préprod refuse
    en content_filter sur claude-opus-5-5 dès que max_tokens est grand (mesuré le 2026-10-05)."""
    provider = PROVIDERS[provider_name]
    env_name = provider.get("base_url_env")
    return (os.environ.get(env_name) if env_name else None) or provider.get("base_url")


def stream(
    model: str,
    system: str,
    messages: list,
    tool_schemas: list,
    config: dict,
) -> Generator:
    provider_name, model_name = resolve_provider(model)
    # liste blanche des fournisseurs, avant toute clé et toute requête.
    check_provider_allowed(provider_name, model)
    # Validate the key up front: a missing key must raise before the first yield.
    api_key = _require_key(provider_name, config)
    native = model_uses_native_tools(model, config)

    from ....xml_tool_protocol import build_tool_docs
    from ....core.context import build_stable_system_prompt
    from ....context_manager import build_verbatim_audit_note
    from ....context_manager.state import METHODOLOGY_NOTE
    from ....context_manager.methodology import build_methodology_system_blocks
    from ....context_manager.contexte_fige import contexte_de_l_appel

    context_state = config.get("_context_state")
    # Un prompt fourni par l'appelant est la moitié STABLE (repl/runner web :
    # `build_stable_system_prompt`). Le contexte de session n'est rajouté que pour un tour
    # d'agent — un appel annexe (compaction, juge, validateur) n'en a pas l'usage — et il
    # l'est EN DERNIER (bloc `volatile` ci-dessous). Il est FIGÉ au premier appel de la session
    # (contexte_fige.py) : ses changements sont empilés en fin de note Methodology, lue juste
    # après — ils entrent dans son delta à cache_control une fois, puis restent en cache.
    stable_prefix = system or build_stable_system_prompt(config)
    #  config["session_context"] = False : un agent hôte (Focus) n'a ni répertoire ni
    #  branche à connaître — le bloc ne ferait que l'égarer (« pas de worktree… »).
    with_context = not system or (bool(tool_schemas) and config.get("session_context", True))
    volatile = contexte_de_l_appel(config, context_state) if with_context else ""
    if with_context and context_state is not None:
        # La mémoire du system est figée (memoire_figee.py) ; relue à chaque appel, un fichier
        # mémoire écrit en cours de tour devient une note dès l'appel suivant.
        from ....context_manager.memoire_figee import memoire_de_l_appel
        memoire_de_l_appel(context_state)
    # The top-level agent (depth 0) is the code-development agent: append the
    # `default` profile's system_prompt_extra (TDD, tests, discovery, interdicts)
    # on top of the shared noyau. Sub-agents (depth > 0) inherit only the noyau and
    # apply their own profile, so this never leaks into them. A host agent that
    # brings its own prompt (Focus) opts out with config["agent_profile_extra"] = False.
    if config.get("_depth", 0) == 0 and config.get("agent_profile_extra", True):
        from ....core.context import get_agent_profile_extra
        classification = config.get("_task_classification_result", "default")
        profile_extra = get_agent_profile_extra(classification)
        if profile_extra:
            stable_prefix = f"{stable_prefix.rstrip()}\n\n{profile_extra}"
    # In native mode tools are sent via the API `tools` param, so the XML tool docs
    # block is redundant — keep it empty to avoid duplicating the schemas.
    tool_docs = "" if native else build_tool_docs(
        tool_schemas or [], config.get("tool_docs_full_names"))
    native_tools = None
    if native and provider_name == "anthropic":
        from .anthropic_native import tool_schemas_to_anthropic
        native_tools = tool_schemas_to_anthropic(tool_schemas or [])
    elif native:
        from .openrouter_native import tool_schemas_to_openai
        native_tools = tool_schemas_to_openai(tool_schemas or [])

    methodology_text = ""
    notes_block = ""
    if context_state and context_state.notes:
        methodology_text = context_state.notes.get(METHODOLOGY_NOTE, "") or ""
        other_notes = {n: c for n, c in context_state.notes.items() if n != METHODOLOGY_NOTE}
        if other_notes:
            notes_block = "[Your working memory notes]\n" + "\n\n".join(
                f"## {name}\n{content}" for name, content in other_notes.items()
            ) + "\n[/Notes]"
    # Consignes du harnais (« A SNIPPETER », destruction, inventaire Verbatim) : un bloc
    # <harness_notes> APRÈS les tool_results, jamais dedans (refus content_filter, 2026-10-07).
    # Les changements de contexte de session (worktree, cd, mémoire) n'y passent PAS : ils ont
    # été empilés ci-dessus dans la note (contexte_fige.empiler_note_de_contexte), donc en cache.
    messages = avec_les_notes_du_harnais(messages, build_verbatim_audit_note(messages))

    # Le « rappel frais » de fin de payload a été retiré le 2026-10-05 : collé au dernier
    # tool_result, il déclenchait le content_filter du gateway sur claude-opus-5-5 (6/6 refus
    # avec, 0/14 sans ; Methodology et Snippet restent appelés sur consigne du system).
    # Rien n'est plus ajouté au fil ; drop_prompt_echo reste branché pour un futur ajout.
    injected_texts: list[str] = []
    # Les consignes « Methodology d'abord / finir par un tool_use » ne valent que pour un
    # tour d'AGENT. Un appel annexe (compaction, juge, resume) n'a aucun outil.
    appel_agent = bool(tool_schemas)

    base_url = provider_base_url(provider_name)
    cache_control = _resolve_cache_control(base_url)
    snapshot = getattr(context_state, "_methodology_cache_snapshot", "") if context_state else ""
    meth_blocks, meth_delta = build_methodology_system_blocks(
        methodology_text, snapshot, cache_control,
    )
    # Seed placeholder: when methodology is empty, inject a transitional hint
    # to reduce first-turn tool-call omission (82% when meth=0).
    seed_placeholder = ""
    if appel_agent and not meth_blocks and os.environ.get(
            "BOUZECODE_SEED_METHODOLOGY", "1") != "0":
        seed_placeholder = (_SEED_METHODOLOGY_PLACEHOLDER_NATIVE if native
                            else _SEED_METHODOLOGY_PLACEHOLDER)
    delta_block = (
        [{"type": "text", "text": meth_delta, "cache_control": cache_control}]
        if meth_delta else []
    )
    # La note (et son amorce, ses voisines) quitte le system : en <working_notes> en tête du
    # premier message user, ses cache_control conservés. Écrite par le modèle et lue en rôle
    # system, elle faisait refuser claude-opus-5-5 (content_filter, rejeux du 2026-10-07).
    note_parts = parties_de_la_note([*meth_blocks, *delta_block], [seed_placeholder, notes_block])
    wire_sans_note = messages
    messages = avec_la_note(messages, note_parts)
    system_blocks = [
        {"type": "text", "text": stable_prefix, "cache_control": cache_control},
        {"type": "text", "text": tool_docs, "cache_control": cache_control},
        {"type": "text", "text": volatile},
    ]
    # In native mode tool_docs is empty, and an empty text block (worse, one carrying
    # a cache_control breakpoint) is rejected by the API. Drop the blanks — this also
    # removes the empty `volatile` block that side-calls have always sent.
    system_blocks = [b for b in system_blocks if b.get("text", "").strip()]
    if appel_agent and native and _regle_finale(provider_name):
        system_blocks.append({"type": "text", "text": _NATIVE_METH_RULE})
    from ..types import SystemPayload
    # Blocs STABLES en tête (préfixe, doc XML des outils) : seuls eux restent dans le system
    # OpenAI, pour que les outils sérialisés après lui restent en cache (cf. stream_openrouter).
    stables = sum(1 for t in (stable_prefix, tool_docs) if t.strip())
    # « note » = l'enveloppe <working_notes> ; « messages » = le fil SANS elle : elle grandit à
    # chaque tour et ferait passer le premier message pour réécrit.
    empreinte = _empreinte(provider_name, stable_prefix, native_tools, tool_docs,
                           note_parts, wire_sans_note)
    # Expose the mutated wire `messages` (<working_notes> and <harness_notes> added above) so
    # the loop can dump the EXACT payload sent to the API, not the pre-mutation copy.
    yield SystemPayload(system_blocks, tools=native_tools, messages=messages, empreinte=empreinte)

    if provider_name == "openrouter":
        from .openrouter_stream import stream_openrouter
        # BOUZECODE_NOTE_DANS_SYSTEM=1 garde contexte de session et règle finale dans le system
        # (état d'avant pour ces deux-là ; la note, elle, est toujours dans le fil).
        source = stream_openrouter(
            api_key, model_name, system_blocks, messages, tool_schemas, config,
            stable_blocks=0 if os.environ.get("BOUZECODE_NOTE_DANS_SYSTEM") == "1" else stables,
            native=native,
        )
    elif provider_name == "gateway_preprod":
        # Internal OpenAI-compatible gateway preprod: reuse the OpenAI streamer but
        # point at PREPROD_ENDPOINT/v1 and bypass the external NTLM proxy.
        from .openrouter_stream import stream_openrouter
        from .openrouter_transport import build_plain_session
        pp_base = (provider_base_url("gateway_preprod") or "").rstrip("/")
        pp_config = config
        reasoning_effort = None
        if model_name.startswith("gpt-5"):
            # GPT-5 reasoning models reason server-side (hidden) and won't emit any
            # visible text until that's done; with a tiny budget the whole thing is
            # consumed by reasoning and the reply comes back empty (finish=length).
            # `high` effort gives deeper planning (better at deciding when a task is
            # complete); a 6000-token floor is enough for reasoning + answer even at
            # high (measured: ~500-1000 reasoning tokens, finish=stop at 6000).
            reasoning_effort = "high"
            if config.get("max_tokens", 8192) < 6000:
                pp_config = {**config, "max_tokens": 6000}
        source = stream_openrouter(
            api_key, model_name, system_blocks, messages, tool_schemas, pp_config,
            base_url=f"{pp_base}/v1", session_factory=build_plain_session,
            send_reasoning=False,  # Azure/LiteLLM rejects the `reasoning` param
            reasoning_effort=reasoning_effort, provider_label="gateway preprod",
        )
    elif provider_name == "gateway_openai":
        # Prod gateway gpt-5.6-* are OpenAI-compatible: the prod Anthropic
        # pass-through crashes in streaming (LiteLLM IndexError), so use the OpenAI
        # streamer pointed at the PROD endpoint (ANTHROPIC_BASE_URL) directly (no
        # NTLM proxy). Same GPT-5 reasoning handling as gateway preprod.
        from .openrouter_stream import stream_openrouter
        from .openrouter_transport import build_plain_session
        prod_base = (PROVIDERS["gateway_openai"].get("base_url") or "").rstrip("/")
        prod_config = config
        reasoning_effort = None
        if model_name.startswith("gpt-5"):
            reasoning_effort = "high"
            if config.get("max_tokens", 8192) < 6000:
                prod_config = {**config, "max_tokens": 6000}
        source = stream_openrouter(
            api_key, model_name, system_blocks, messages, tool_schemas, prod_config,
            base_url=f"{prod_base}/v1", session_factory=build_plain_session,
            send_reasoning=False,  # Azure/LiteLLM rejects the `reasoning` param
            reasoning_effort=reasoning_effort, provider_label="gateway prod",
        )
    else:
        source = stream_anthropic(
            api_key, model_name, system_blocks, messages, tool_schemas, config,
            base_url=base_url, cache_last=False, native_tools=native_tools,
        )
    for event in cut_at_role_leak(
        drop_prompt_echo(source, injected_texts), native_tools=native,
    ):
        _record_side_call(config, model, event, empreinte)
        yield event
    if context_state and methodology_text:
        context_state._methodology_cache_snapshot = methodology_text


def _empreinte(provider_name: str, stable_prefix: str, native_tools: list | None,
               tool_docs: str, blocs_note: list[dict], messages: list) -> dict:
    """Empreintes du préfixe tel qu'envoyé (cf. empreinte.py). Anthropic lit les outils natifs
    AVANT le système ; les chat templates OpenAI-compatibles, après."""
    from .empreinte import calculer
    outils_en_tete = provider_name == "anthropic" and bool(native_tools)
    ordre = ("tools", "system") if outils_en_tete else ("system", "tools")
    # La note telle que lue sur le fil : l'enveloppe <working_notes> en tête du premier message
    # user, parties bout à bout (note + delta : le texte du tour N est un préfixe de celui du
    # tour N+1). Sa tête cachable s'arrête à la dernière partie à cache_control.
    tete = "".join(b["text"] for b in blocs_note if b.get("cache_control"))
    parties = {"system": stable_prefix,
               "tools": native_tools if native_tools is not None else tool_docs,
               "note": "".join(b["text"] for b in blocs_note)}
    return calculer((*ordre, "note", "messages"), parties, messages, note_stable=len(tete))


def _record_side_call(config: dict, model: str, event, empreinte: dict | None = None) -> None:
    """Journalise l'usage d'un appel ANNEXE (copie de la config de la boucle) dans le
    compaction_log de la session : ces appels sont facturés comme les autres, mais la
    boucle ne les voyait pas — /api/sessions/<key>/costs les ignorait donc."""
    from ..types import AssistantTurn
    if not isinstance(event, AssistantTurn):
        return
    main_id = config.get("_main_config_id")
    state = config.get("_state")
    if main_id is None or main_id == id(config) or state is None:
        return
    import time
    from .empreinte import completer
    entree = {
        "event": "side_call", "timestamp": time.time(),
        "turn": getattr(state, "turn_count", 0), "model": model,
        "label": config.get("_call_label") or "",
        "api_input_tokens": event.in_tokens, "api_output_tokens": event.out_tokens,
        "api_cache_read": event.cache_read_tokens, "api_cache_create": event.cache_creation_tokens,
        "provider": getattr(event, "provider", ""),
    }
    # Même règle que l'appel principal (loop._usage_of_call) : un usage jamais reçu est
    # estimé et marqué, jamais servi à 0.
    if not event.out_tokens and event.text:
        entree["api_output_tokens"] = -(-len(event.text) * 2 // 7)
        entree["api_output_estimated"] = True
    elif getattr(event, "out_tokens_estimated", False):
        entree["api_output_estimated"] = True
    longueurs = (empreinte or {}).get("longueurs") or {}
    if not (event.in_tokens or event.cache_read_tokens or event.cache_creation_tokens) and longueurs:
        entree["api_input_tokens"] = -(-sum(v for v in longueurs.values()
                                             if isinstance(v, int)) * 2 // 7)
        entree["api_input_estimated"] = True
    completer(entree, empreinte, state)
    state.compaction_log.append(entree)
