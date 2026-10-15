# [desc] Coupe le tour dès que le modèle se met à écrire le tour du harnais [/desc]
"""Garde-fou contre la fabrication des résultats d'outils par le modèle.

Le protocole XML fait émettre les appels d'outils DANS le texte de l'assistant. Le
modèle doit s'arrêter après ses balises ; le harnais exécute, puis lui rend les
résultats au tour suivant. Rien ne l'y oblige : il peut enchaîner et écrire
lui-même la suite de la conversation — le résultat de l'outil, le tour user, ses
propres rappels — puis raisonner dessus jusqu'à la réponse finale.

Ce qu'on coupe n'est PAS la fin d'un appel (couper à `</tool_use>` interdirait les
lots parallèles, que le protocole encourage) : c'est le moment où le modèle change
de rôle. Ce moment est repérable au caractère près, par la règle de prompt_echo
poussée d'un cran : un texte que le harnais écrit lui-même n'est jamais du contenu
du modèle. prompt_echo SUPPRIME la ligne ; ici on COUPE le tour, parce que la
suppression est cosmétique — elle cache le texte sans empêcher le modèle de
continuer à raisonner sur sa fiction, ni cette fiction d'entrer dans l'historique.

Les appels déjà parsés avant la coupe sont conservés et exécutés normalement : le
tour se termine sans clôture, la boucle repart, et les VRAIS résultats arrivent.
"""
from __future__ import annotations

import sys

from ..types import AssistantTurn, TextChunk, ThinkingChunk, ToolCallParsed

# Chacun de ces fragments est écrit par le harnais lui-même — jamais par un modèle
# qui répond à une question. Les voir sortir du modèle, c'est le voir jouer le
# harnais. `<tool_result` est absent volontairement : c'est la balise que
# `serialize_tool_result` produit, et XmlToolStreamParser l'avale déjà.
ROLE_LEAK_MARKERS = (
    "<tool_use_result",            # near-miss de <tool_result> : conv. 6e67be34, 2dedf996
    "==== A SNIPPETER id:",        # marqueur de wire (snippet_wire._SNIPPET_OPEN)
    "[[ Résultats des tools",      # en-tête de lot de résultats — conv. cb6eed86
    "[RAPPEL] Tu n'as pas encore", # relance du harnais — conv. 9c13b909
    "(System Automated Event):",   # préfixe des messages système de loop_turn
)

_LONGEST_MARKER = max(len(m) for m in ROLE_LEAK_MARKERS)

# Le marqueur arrive collé au NOM DU RÔLE que le modèle vient d'endosser
# (`tool<tool_use_result`, `user[RAPPEL]`, `système<system>`) : le template de chat
# rend le délimiteur de rôle en texte brut. Ce nom fait partie de la fuite.
_ROLE_TOKENS = ("système", "assistant", "system", "human", "tool", "user")


def find_role_leak(text: str) -> int:
    """Offset du début de la première fuite de rôle dans *text*, ou -1."""
    hits = [i for i in (text.find(m) for m in ROLE_LEAK_MARKERS) if i != -1]
    if not hits:
        return -1
    start = min(hits)
    head = text[:start].lower()
    for role in _ROLE_TOKENS:
        if head.endswith(role):
            return start - len(role)
    return start


def _held_prefix_length(text: str) -> int:
    """Longueur du suffixe de *text* qui pourrait encore devenir un marqueur.

    Un marqueur coupé entre deux chunks (`tool<tool_use` + `_result id=...`) doit
    être reconnu : on retient la fin du tampon tant qu'elle est le début d'un
    marqueur, exactement comme le fait le scanner XML.
    """
    for size in range(min(len(text), _LONGEST_MARKER - 1), 0, -1):
        tail = text[-size:]
        if not any(m.startswith(tail) for m in ROLE_LEAK_MARKERS):
            continue
        # Le nom de rôle qui précède part avec le marqueur : le retenir aussi,
        # sinon il aurait déjà été émis quand le marqueur se complète.
        head = text[:-size].lower()
        role = next((r for r in _ROLE_TOKENS if head.endswith(r)), "")
        return size + len(role)
    return 0


def _truncated_turn(turn: AssistantTurn, tool_calls_kept: int | None) -> AssistantTurn:
    """Le tour tel qu'il aurait été si le modèle s'était arrêté à la fuite."""
    cut = find_role_leak(turn.text or "")
    text = turn.text[:cut] if cut != -1 else turn.text
    calls = turn.tool_calls if tool_calls_kept is None else turn.tool_calls[:tool_calls_kept]
    coupe = AssistantTurn(
        text, calls, turn.in_tokens, turn.out_tokens,
        turn.cache_read_tokens, turn.cache_creation_tokens, turn.stop_reason,
    )
    coupe.provider = getattr(turn, "provider", "")
    return coupe


def cut_at_role_leak(events, native_tools: bool = False):
    """Interrompt le texte du tour au premier marqueur de fuite de rôle.

    *native_tools* : en tool-calling natif les appels arrivent hors du texte, donc
    leur position par rapport à la fuite ne veut rien dire — on coupe le texte mais
    on garde tous les appels.
    """
    cut = False
    held = ""
    tools_before_cut = 0
    for event in events:
        if isinstance(event, AssistantTurn):
            if cut:
                yield _truncated_turn(event, None if native_tools else tools_before_cut)
            else:
                yield event
            continue
        if cut:
            if isinstance(event, (TextChunk, ThinkingChunk, ToolCallParsed)):
                continue
            yield event
            continue
        if isinstance(event, ToolCallParsed):
            tools_before_cut += 1
            yield event
            continue
        if not isinstance(event, TextChunk):
            yield event
            continue
        buffer = held + event.text
        leak = find_role_leak(buffer)
        if leak != -1:
            cut = True
            held = ""
            _warn_leak(buffer[leak:])
            if buffer[:leak]:
                yield TextChunk(buffer[:leak])
            continue
        held_len = _held_prefix_length(buffer)
        emitted, held = buffer[:len(buffer) - held_len], buffer[len(buffer) - held_len:]
        if emitted:
            yield TextChunk(emitted)
    if held and not cut:
        yield TextChunk(held)


def _warn_leak(tail: str) -> None:
    """Un tour coupé doit rester visible : il signale un modèle qui s'auto-répond."""
    print(
        "\r\x1b[2K\x1b[1;41;97m[role-leak] le modèle a écrit le tour du harnais — "
        f"tour coupé à : {tail[:60]!r}\x1b[0m",
        file=sys.stderr, flush=True,
    )
