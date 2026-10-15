# [desc] Transcription des conversations bouzecode() simulées, ajoutée au rapport pytest quand le test échoue. [/desc]
"""Quand un test fondé sur `bouzecode()` échoue, montrer ce qui s'est passé dans la conversation.

Sans ça, un échec ne dit rien de ce que les outils ont réellement renvoyé : un Bash refusé
par PowerShell 5.1 ou un `sh` introuvable restaient invisibles, et il fallait vider la sortie
à la main dans un fichier pour les découvrir. Le harnais enregistre chaque conversation dès
son démarrage (`enregistrer`) ; les hooks ci-dessous, importés par `tests/conftest.py`,
ajoutent la transcription au rapport d'un test en échec, y compris quand le harnais lui-même
a levé (file MockLLM épuisée) — l'état est lu en direct, pas au retour.
"""
from __future__ import annotations

import json
import os
import re

import pytest

from bouzecode.backend.agent.demande_en_cours import DEMANDE_UTILISATEUR
from bouzecode.backend.agent.state import ToolEnd

LIMITE_RESULTAT = 500
LIMITE_ARGUMENT = 160
LIMITE_MESSAGE = 400
TITRE_SECTION = "bouzecode() conversation"

_BALISAGE = re.compile(
    r"<thinking>.*?</thinking>|<tool_use\b.*?</tool_use>|<tool_use\b[^>]*/>", re.DOTALL,
)

_conversations: list[dict] = []


def enregistrer(state, events: list, mock_llm=None) -> None:
    """Le harnais déclare une conversation qui démarre ; `state` et `events` se remplissent ensuite."""
    _conversations.append({"state": state, "events": events, "mock_llm": mock_llm})


def oublier() -> None:
    _conversations.clear()


def _abreger(texte, limite: int) -> str:
    texte = str(texte)
    if len(texte) <= limite:
        return texte
    return f"{texte[:limite]}… [+{len(texte) - limite} car.]"


def _arguments(inputs: dict) -> str:
    morceaux = []
    for cle, valeur in (inputs or {}).items():
        if not isinstance(valeur, str):
            valeur = json.dumps(valeur, ensure_ascii=False)
        morceaux.append(f"{cle}={_abreger(valeur, LIMITE_ARGUMENT)!r}")
    return ", ".join(morceaux)


def _texte(content) -> str:
    if isinstance(content, list):
        content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content or "")


def _imprimable(texte: str) -> str:
    """Une console Windows en cp1252 qui croise UN caractère hors table voit pytest échapper TOUTE
    la section en `\\uXXXX` sur une seule ligne : on n'échappe que les caractères fautifs."""
    if os.name != "nt":
        return texte
    return texte.encode("cp1252", "backslashreplace").decode("cp1252")


def _decaler(texte: str, marge: str) -> str:
    return "\n".join(marge + ligne for ligne in texte.splitlines() or [""])


def _ligne_message(message: dict, resultats_bruts: dict) -> list[str]:
    role = message.get("role")
    if role == "user":
        etiquette = "[user]" if message.get(DEMANDE_UTILISATEUR) else "[harness -> modèle]"
        return [f"{etiquette} {_abreger(_texte(message.get('content')), LIMITE_MESSAGE)}"]
    if role == "assistant":
        visible = _BALISAGE.sub("", _texte(message.get("content"))).strip()
        lignes = [f"[assistant] {_abreger(visible, LIMITE_MESSAGE)}" if visible else "[assistant]"]
        for appel in message.get("tool_calls") or []:
            lignes.append(f"  -> {appel.get('name')}({_arguments(appel.get('input'))})")
        return lignes
    if role == "tool":
        resultat = resultats_bruts.get(message.get("tool_call_id"), message.get("content"))
        corps = _decaler(_abreger(_texte(resultat), LIMITE_RESULTAT), "      ")
        return [f"    <= {message.get('name')} :", corps]
    return [f"[{role}] {_abreger(_texte(message.get('content')), LIMITE_MESSAGE)}"]


def rendre_conversation(conversation: dict) -> str:
    state = conversation["state"]
    resultats_bruts = {e.tool_id: e.result for e in conversation["events"]
                       if isinstance(e, ToolEnd) and e.tool_id}
    lignes = []
    for message in state.messages:
        lignes.extend(_ligne_message(message, resultats_bruts))
    mock = conversation["mock_llm"]
    if mock is not None:
        lignes.append(f"MockLLM : {mock.call_index}/{len(mock.responses)} réponses consommées, "
                      f"{mock.side_calls} appel(s) annexe(s)")
    cloture = state.close_reason or "(aucune : la conversation ne s'est pas close)"
    lignes.append(f"close_reason : {cloture}")
    if state.close_detail:
        lignes.append(f"close_detail : {_abreger(state.close_detail, LIMITE_MESSAGE)}")
    return "\n".join(lignes)


def rendre_tout() -> str:
    total = len(_conversations)
    texte = "\n\n".join(
        f"-- conversation {rang}/{total} --\n{rendre_conversation(c)}"
        for rang, c in enumerate(_conversations, 1)
    )
    return _imprimable(texte)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    oublier()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    resultat = yield
    rapport = resultat.get_result()
    if rapport.when == "call" and rapport.failed and _conversations:
        rapport.sections.append((TITRE_SECTION, rendre_tout()))
