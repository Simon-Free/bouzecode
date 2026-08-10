# [desc] Trace par tour de ce qui part au LLM, écrite en DELTAS (la lecture est une vue, cf. core/payload_view). [/desc]
"""Écrit ce qui est réellement envoyé au modèle à chaque appel.

`state.last_api_payload` ne garde que le dernier appel. Quand le modèle déraille au 80e tour,
il faut la trace complète — d'où ce journal `~/.bouzecode/debug_payloads/<session_id>/
turns.jsonl`, un objet JSON par ligne, deux par tour (un avant le stream, un enrichi après).

LE CONTEXTE D'UN TOUR EST UNE VUE, PAS UNE DONNÉE STOCKÉE. Chaque enregistrement portait le
tableau `messages` ENTIER, c'est-à-dire toute la conversation telle que le modèle la voyait à
cet instant. Le journal grossissait donc en O(tours²). Mesuré sur une session réelle : 219 Mo
pour 431 enregistrements, dont le dernier — le seul contenant l'état complet — pèse 1 Mo. Sur
le parc : 3 191 sessions, 8 Go.

Le fichier ne garde plus que ce qui CHANGE d'un enregistrement au suivant :

    {"turn": N, "timestamp": …, "keep": K, "append": [msg, …], "system_blocks": …}

`keep` = nombre de messages de tête identiques à l'enregistrement précédent, `append` = la
suite. Un enregistrement peut toujours être ABSOLU (clé `messages`) : c'est le cas du premier,
de celui qui suit une reprise de process, et de tout ce qui a été écrit avant ce changement.

POURQUOI CETTE FORME-LÀ, et pas un diff générique : `context_viewer` calcule déjà
`_payload_divergence(prev, cur)` — l'indice à partir duquel le payload courant s'écarte du
précédent — pour décider quels éléments sont `cached` ou `fresh`. `keep` EST cette divergence.
Le delta ne fait que matérialiser un raisonnement que le lecteur tenait déjà, et une compaction
(qui réécrit la tête) se décrit toute seule : `keep` petit, `append` gros.

La LECTURE vit dans `core/payload_view.py` — délibérément hors de ce paquet, pour qu'un lecteur
n'ait pas à importer toute la boucle d'agent (et son registre de plugins) pour lire un fichier.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..core.payload_view import payload_dir as _payload_dir  # noqa: F401 — ré-export
from ..core.payload_view import to_refs

# Dernier payload écrit, PAR session, dans CE process. Base du delta suivant. Vide au
# démarrage : le premier enregistrement d'un process est donc toujours absolu — on ne calcule
# jamais un delta contre un état qu'on n'a pas lu.
_last_payload: dict[str, list] = {}

# Empreintes des blocs de texte DÉJÀ écrits, PAR session, dans CE process. Même prudence que
# ci-dessus : vide au démarrage, donc une reprise de process réécrit les blocs une fois — ce
# qui coûte un enregistrement gros et garantit qu'aucune référence ne pend dans le vide.
_blocs_connus: dict[str, set] = {}


def _common_prefix_length(previous: list, current: list) -> int:
    """Nombre de messages de tête IDENTIQUES entre deux payloads.

    Comparaison par sérialisation stable : les messages sont des dicts imbriqués, et deux
    dicts égaux doivent donner la même clé quel que soit leur ordre d'insertion."""
    limite = min(len(previous), len(current))
    for i in range(limite):
        if json.dumps(previous[i], sort_keys=True, default=str) != \
                json.dumps(current[i], sort_keys=True, default=str):
            return i
    return limite


def _payload_fields(session_id: str, messages: list) -> dict:
    """Les champs décrivant le payload : delta si le précédent est connu, sinon absolu."""
    previous = _last_payload.get(session_id)
    _last_payload[session_id] = list(messages)
    if previous is None:
        return {"messages": messages}
    keep = _common_prefix_length(previous, messages)
    return {"keep": keep, "append": messages[keep:]}


def dump_turn_payload(state, session_id: str, messages: list,
                      system_blocks: list | None = None,
                      token_counts: dict | None = None) -> None:
    if not session_id:
        return
    target_dir = Path(_payload_dir(session_id))
    target_dir.mkdir(parents=True, exist_ok=True)
    # Blocs de texte DÉJÀ écrits dans ce journal : on ne réécrit que les nouveaux.
    connus = _blocs_connus.setdefault(session_id, set())
    blobs: dict[str, str] = {}
    record = {
        "turn": state.turn_count,
        "timestamp": time.time(),
        **_payload_fields(session_id, messages),
        "notes_refs": {cle: to_refs(str(texte), blobs, connus)
                       for cle, texte in (state.context_state.notes or {}).items()},
    }
    if system_blocks is not None:
        record["system_blocks_refs"] = [
            {**{k: v for k, v in bloc.items() if k != "text"},
             "refs": to_refs(str(bloc.get("text", "")), blobs, connus)}
            if isinstance(bloc, dict) else {"refs": to_refs(str(bloc), blobs, connus)}
            for bloc in system_blocks
        ]
    if token_counts is not None:
        record["token_counts"] = token_counts
    if blobs:
        record["blobs"] = blobs
    with (target_dir / "turns.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
