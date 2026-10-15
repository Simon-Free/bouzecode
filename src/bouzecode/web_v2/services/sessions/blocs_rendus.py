# [desc] Mémoire du HTML rendu des messages d'une session (fil d'un agent) : un message n'est rendu qu'une fois par contenu. [/desc]
"""Le fil d'un agent (`/api/sessions/<key>/blocks`) rendait TOUS ses messages à chaque
ouverture : 7 à 8 s pour une session de 78 Mo, dont la moitié à redécouper la réflexion des
messages assistant. Le HTML d'un message ne dépend que du message et de son lien vers le
diagnostic de contexte : il est mémorisé par (chemin de session, indice), avec une empreinte
du message — un message réécrit (sauvegarde progressive du dernier tour) est rendu à nouveau.

Bornes : les `_MAX_SESSIONS` dernières sessions ouvertes, et `_BUDGET_OCTETS` de HTML en tout
(une session de 78 Mo rendue en entier en pèse 51) — la session la plus ancienne part d'abord,
jamais celle qu'on sert. L'empreinte est `hash(repr(message))`,
valable le temps du process (le hachage des chaînes est salé par process) : elle n'est jamais
écrite nulle part.
"""
from __future__ import annotations

import threading
from collections import OrderedDict

from .. import message_view

_MAX_SESSIONS = 6
_BUDGET_OCTETS = 64 * 1024 * 1024
_memo: "OrderedDict[str, dict[int, tuple[int, str | None, str]]]" = OrderedDict()
_tailles: dict[str, int] = {}   # chemin → caractères de HTML gardés
_verrou = threading.Lock()


def rendre(chemin: str, indice: int, message: dict, context_url: str | None) -> str:
    """HTML du message `indice` de la session `chemin` (rendu une fois par contenu)."""
    empreinte = hash(repr(message))
    with _verrou:
        connu = (_memo.get(chemin) or {}).get(indice)
    if connu is not None and connu[0] == empreinte and connu[1] == context_url:
        return connu[2]
    rendu = message_view.render_message(message, context_url=context_url)
    with _verrou:
        par_indice = _memo.setdefault(chemin, {})
        ancien = par_indice.get(indice)
        par_indice[indice] = (empreinte, context_url, rendu)
        _tailles[chemin] = _tailles.get(chemin, 0) + len(rendu) - (len(ancien[2]) if ancien else 0)
        _memo.move_to_end(chemin)
        while len(_memo) > 1 and (len(_memo) > _MAX_SESSIONS
                                  or sum(_tailles.values()) > _BUDGET_OCTETS):
            parti, _ = _memo.popitem(last=False)
            _tailles.pop(parti, None)
    return rendu


def oublier() -> None:
    """Vide la mémoire (tests)."""
    with _verrou:
        _memo.clear()
        _tailles.clear()
