# [desc] Chaîne de repli sur refus du modèle : le tour refusé est d'abord rejoué avec la note compactée sur le même modèle, puis sur la marche suivante (opus-5-5 -> sonnet-5-5 -> opus-5), une tentative par variante et par tour au plus. [/desc]
"""Chaîne de repli de modèle sur refus (`content_filter` / `refusal`).

Un refus est propre à UN modèle et à un contexte (claude-opus-5-5 : 12/12 sur le payload
de b2feb0ff, claude-opus-5 : 0/6). La chaîne d'un modèle (`refusal_chain`) suit les liens
de `providers.registry.REFUSAL_FALLBACK` : claude-opus-5-5 -> claude-sonnet-5-5 ->
claude-opus-5. `serve_on_chain` sert le tour sur une marche de départ puis, à chaque refus,
le rejoue sur la marche suivante, sur le même état (messages, system, outils ; le fil est
reconstruit par `stream_turn` pour le transport de la marche). Chaque marche est tentée
UNE fois par tour au plus : chaque tentative refusée est facturée. Chaîne épuisée = le
dernier tour refusé reste dans `ctx`, et `handle_no_tools` ferme en `content_refusal`.

Note compactée d'abord (session 28738fd0) : le refus est DÉTERMINISTE pour un contexte
donné et vient de la note accumulée ; changer de modèle n'y suffit pas toujours (opus-5
refusait le tour 11 à 11/12, comme sonnet-5-5), la note compactée le fait tomber (12/12 ->
0/10). Au premier refus du tour, la note est compactée (`context_manager.note_compactee`,
état durable) et le tour rejoué UNE fois sur la MÊME marche ; encore refusé, il glisse sur
la marche suivante, avec la note compactée. Rien à compacter = pas de rejeu (même payload).
"""
from __future__ import annotations

import os
import sys
import time
from typing import Generator

from ..context_manager.note_compactee import compacter_la_note_sur_refus
from .loop_context import LoopContext, TurnAction
from .providers import StreamRestart
from .providers.registry import (
    REFUSAL_FALLBACK, allowed_providers, bare_model, get_provider_key, resolve_provider,
)
from .state import AgentState

REFUSAL_FALLBACK_ENV = "BOUZECODE_REFUSAL_FALLBACK"
# Borne de la chaîne (marches de repli, principal non compris) : un cycle ou une surcharge
# trop longue ne peut pas faire rejouer un tour plus de MAX_MARCHES_DE_REPLI fois.
MAX_MARCHES_DE_REPLI = 3
# Variante de rejeu sur refus, journalisée dans turns.jsonl (`appel.variante`).
VARIANTE_NOTE_COMPACTEE = "note_compactee"


def is_refused_turn(ctx: LoopContext) -> bool:
    """Tour complet, sans appel d'outil, que le modèle (ou le filtre) a refusé."""
    turn = ctx.assistant_turn
    if turn is None or turn.tool_calls or ctx.action == TurnAction.BREAK or ctx.thinking_overflow:
        return False
    return getattr(turn, "stop_reason", None) == "content_filter" or bool(getattr(turn, "refusal", None))


def refusal_chain(model: str, config: dict) -> list[str]:
    """Les marches de repli de `model`, dans l'ordre : config > env > table du registre.

    Une surcharge est un modèle (chaîne d'une marche, l'ancien comportement), une liste,
    ou « a,b » ; `none` coupe. Une marche dont le fournisseur est hors liste blanche ou
    sans clé est sautée : la rejouer lèverait au lieu de fermer en `content_refusal`.
    Sans doublon ni retour sur `model`, bornée à MAX_MARCHES_DE_REPLI."""
    override = config.get("refusal_fallback") or os.environ.get(REFUSAL_FALLBACK_ENV, "").strip()
    if isinstance(override, str):
        if override.lower() == "none":
            return []
        override = [name.strip() for name in override.split(",") if name.strip()]
    candidates = list(override) if override else _registry_chain(model)
    chain: list[str] = []
    seen = {bare_model(model)}
    for candidate in candidates:
        if bare_model(candidate) in seen or len(chain) >= MAX_MARCHES_DE_REPLI:
            continue
        seen.add(bare_model(candidate))
        if _is_servable(candidate, config):
            chain.append(candidate)
    return chain


def _registry_chain(model: str) -> list[str]:
    """Les liens de REFUSAL_FALLBACK suivis depuis `model`, arrêtés au premier modèle déjà
    vu (pas de boucle) et bornés."""
    chain: list[str] = []
    seen = {bare_model(model)}
    successor = REFUSAL_FALLBACK.get(bare_model(model))
    while successor and bare_model(successor) not in seen and len(chain) < MAX_MARCHES_DE_REPLI:
        chain.append(successor)
        seen.add(bare_model(successor))
        successor = REFUSAL_FALLBACK.get(bare_model(successor))
    return chain


def _is_servable(model: str, config: dict) -> bool:
    provider_name = resolve_provider(model)[0]
    allowed = allowed_providers()
    if allowed is not None and provider_name not in allowed:
        return False
    return bool(get_provider_key(provider_name, config))


def serve_on_chain(state: AgentState, config: dict, system_prompt: str, ctx: LoopContext,
                   cancel_check, stream_turn, marches: list[str], depart: int) -> Generator:
    """Sert le tour sur `marches[depart]`, puis sur la marche suivante à chaque refus.

    `marches[0]` est le modèle de la session (`config["model"]`). Rend (valeur de retour
    du générateur) l'indice de la marche qui a répondu, None si toutes ont refusé."""
    from .loop import _account_llm_call
    note_compactee_tentee = False
    for indice in range(depart, len(marches)):
        modele = marches[indice]
        if indice > depart:
            # ASCII seul : ce stderr peut finir dans un fichier cp1252 (runs headless Windows).
            print(f"[bouzecode] refus de {marches[indice - 1]} (content_filter) - tour rejoue "
                  f"avec {modele}", file=sys.stderr)
            yield StreamRestart()
        collee = indice == depart
        yield from _stream_on(state, config, system_prompt, ctx, cancel_check, stream_turn,
                              modele, collee=collee)
        refuse = is_refused_turn(ctx)
        if refuse and not note_compactee_tentee:
            note_compactee_tentee = True
            compaction = compacter_la_note_sur_refus(config)
            if compaction:
                # La tentative refusée est comptée ICI, sous son modèle : le rejeu écrase ctx.
                _account_llm_call(state, config, ctx)
                _tag_last_call(state, modele)
                ctx.accounted_turn = -1
                print(f"[bouzecode] refus de {modele} (content_filter) - note compactee "
                      f"({compaction['chars_retires']} car.), tour rejoue sur {modele}",
                      file=sys.stderr)
                yield StreamRestart()
                yield from _stream_on(state, config, system_prompt, ctx, cancel_check,
                                      stream_turn, modele, collee=collee,
                                      variante=VARIANTE_NOTE_COMPACTEE)
                refuse = is_refused_turn(ctx)
                state.compaction_log.append({
                    "event": "refus_note_compactee", "timestamp": time.time(),
                    "turn": state.turn_count, "model": modele, "refused": refuse, **compaction,
                })
        derniere_marche = indice == len(marches) - 1
        if indice > 0 or (refuse and not derniere_marche):
            # Compté ICI, sous son modèle : la marche suivante écrasera ctx.
            _account_llm_call(state, config, ctx)
            _tag_last_call(state, modele)
        if indice > depart:
            state.compaction_log.append({
                "event": "refusal_fallback", "timestamp": time.time(), "turn": state.turn_count,
                "model": marches[indice - 1], "fallback": modele, "fallback_refused": refuse,
                "marche": indice,
            })
        if not refuse:
            return indice
        if not derniere_marche:
            ctx.accounted_turn = -1  # la tentative suivante du même tour est comptée aussi
    return None


def _stream_on(state: AgentState, config: dict, system_prompt: str, ctx: LoopContext,
               cancel_check, stream_turn, modele: str, collee: bool,
               variante: str = "") -> Generator:
    """Un appel sur `modele`, marqué dans turns.jsonl (loop_turn) : `repli_collant` pour un
    tour servi d'emblée par une marche de repli, `repli_apres_refus` pour un rejeu, et
    `variante` (`note_compactee`) pour un rejeu à note compactée."""
    principal = config["model"]
    drapeaux = {"_variante": variante} if variante else {}
    if modele != principal:
        drapeaux["_repli_collant" if collee else "_appel_de_repli"] = True
    config.update(drapeaux)
    config["model"] = modele
    try:
        yield from stream_turn(state, config, system_prompt, ctx, cancel_check)
    finally:
        config["model"] = principal
        for drapeau in drapeaux:
            config.pop(drapeau, None)


def _tag_last_call(state: AgentState, modele: str) -> None:
    derniere = state.compaction_log[-1] if state.compaction_log else {}
    if derniere.get("event") == "llm_call" and derniere.get("turn") == state.turn_count:
        derniere["model"] = modele
