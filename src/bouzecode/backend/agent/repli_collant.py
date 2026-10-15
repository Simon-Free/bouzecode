# [desc] Repli collant : les tours suivants partent directement sur la dernière marche de la chaîne de repli qui a répondu, jusqu'au prochain allègement du contexte, changement de modèle, ressonde ou chaîne épuisée. [/desc]
"""Repli collant sur refus (`content_filter`).

Session 4b47c33d (2026-10-08) : à partir du tour 25, claude-opus-5-5 a refusé 15 tours sur
15. Le refus vient du CONTEXTE accumulé (la note Methodology est cumulative) : franchi une
fois, il se reproduit à chaque tour. Retenter le principal à chaque tour avant de rejouer
sur le repli a coûté 82 s, 253 k tokens d'entrée et 184 k d'écriture de cache pour rien.

Un rejeu accepté sur une marche de repli (`refusal_fallback.serve_on_chain`) arme donc le
collage (`AgentState.repli_collant`) sur CETTE marche : les tours suivants partent
directement d'elle et, si elle refuse, glissent sur la marche suivante, où le collage se
déplace (session 28738fd0 : sonnet-5-5 collé a refusé aux tours 11 et 12). Il se lève quand :
- le modèle de la session n'est plus le principal refusé (/model) ;
- le contexte a été allégé : /clear (`repartir_de_zero` vide l'état, collage compris) ou
  compaction de la note (`ContextState.allegements` a bougé) ;
- `RESSONDE_TOUS_LES_N_TOURS` tours ont passé : le principal est ressondé une fois. Le
  contexte bouge par d'autres voies que la compaction (messages élagués, note réécrite) ;
  sans ressonde, une longue session resterait collée à vie. Une ressonde refusée coûte
  un appel, soit le dixième de ce que coûtait la retente systématique ;
- la marche collée n'est plus dans la chaîne (liste blanche, surcharge) ;
- la chaîne a été épuisée : toutes les marches tentées ce tour ont refusé.

Nouveau message utilisateur alors qu'une marche est collée : le tour part de la marche
COLLÉE, pas de la tête. Le refus vient du contexte accumulé, qu'un message de plus
n'allège pas ; retenter la tête à chaque message reproduirait le gaspillage de 4b47c33d.
La tête retrouve sa chance par les levées ci-dessus. Si en revanche le tour précédent a
épuisé la chaîne, le collage est levé : rien ne désigne plus une marche comme meilleure
que la tête, et le message de l'utilisateur est le seul changement du contexte — le tour
suivant reprend toute la chaîne depuis la tête, une tentative par marche.
"""
from __future__ import annotations

import sys
import time
from typing import Generator

from .loop_context import LoopContext
from .refusal_fallback import refusal_chain, serve_on_chain
from .state import AgentState

RESSONDE_TOUS_LES_N_TOURS = 10


def tour_llm(state: AgentState, config: dict, system_prompt: str,
             ctx: LoopContext, cancel_check, stream_turn) -> Generator:
    """Un tour LLM servi par la chaîne de repli : depuis la marche collée s'il y en a une,
    sinon depuis le principal. `stream_turn` est le `stream_llm_turn` de la boucle,
    passé tel quel pour que les tests qui le remplacent sur `loop` restent branchés."""
    principal = config["model"]
    marches = [principal, *refusal_chain(principal, config)]
    repli = repli_a_servir(state, config)
    if repli is not None and repli not in marches:
        _lever(state, config, "repli hors de la chaine")
        repli = None
    depart = marches.index(repli) if repli is not None else 0
    servie = yield from serve_on_chain(state, config, system_prompt, ctx, cancel_check,
                                       stream_turn, marches, depart)
    if servie is None:
        if state.repli_collant:
            _lever(state, config, "chaine epuisee")
    elif servie != depart:
        _armer(state, principal, marches[servie])


def repli_a_servir(state: AgentState, config: dict) -> str | None:
    """La marche collée à servir ce tour, ou None — le collage est levé au passage si une
    de ses conditions de levée est remplie."""
    collage = state.repli_collant
    if not collage:
        return None
    raison = _raison_de_lever(collage, state, config)
    if not raison:
        return collage["repli"]
    _lever(state, config, raison)
    return None


def _lever(state: AgentState, config: dict, raison: str) -> None:
    collage = state.repli_collant
    state.compaction_log.append({
        "event": "repli_collant_leve", "timestamp": time.time(), "turn": state.turn_count,
        "model": collage["principal"], "fallback": collage["repli"], "raison": raison,
    })
    print(f"[bouzecode] repli collant leve ({raison}) - retour sur {config.get('model', '')}",
          file=sys.stderr)
    collage.clear()


def _raison_de_lever(collage: dict, state: AgentState, config: dict) -> str:
    if config.get("model") != collage["principal"]:
        return "changement de modele"
    if _allegements(state) != collage["allegements"]:
        return "contexte allege"
    if state.turn_count - collage["depuis_tour"] >= RESSONDE_TOUS_LES_N_TOURS:
        return f"ressonde apres {RESSONDE_TOUS_LES_N_TOURS} tours"
    return ""


def _allegements(state: AgentState) -> int:
    return getattr(state.context_state, "allegements", 0)


def _armer(state: AgentState, principal: str, repli: str) -> None:
    state.repli_collant.clear()
    state.repli_collant.update({
        "principal": principal, "repli": repli, "depuis_tour": state.turn_count,
        "allegements": _allegements(state),
    })
    state.compaction_log.append({
        "event": "repli_collant_arme", "timestamp": time.time(), "turn": state.turn_count,
        "model": principal, "fallback": repli,
    })
    # ASCII seul : ce stderr peut finir dans un fichier cp1252 (runs headless Windows).
    print(f"[bouzecode] {principal} refuse ce contexte : la suite de la session passe sur "
          f"{repli} jusqu'au prochain /clear (ou compaction ; ressonde dans "
          f"{RESSONDE_TOUS_LES_N_TOURS} tours)", file=sys.stderr)

