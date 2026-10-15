# [desc] Mémorise les appels de lecture déjà joués pour ne pas rejouer un échec à l'identique. [/desc]
"""Ne pas refaire deux fois exactement la même chose.

Une session observée a émis trois `WebFetch` sur la même URL — deux d'entre eux
dans le même tour — pour recevoir trois fois la même page de login, puis a
abandonné. Rien ne lui disait qu'elle tournait en rond.

Deux comportements, volontairement asymétriques :

- **Outil de lecture, et rien n'a été écrit depuis** : le résultat ne PEUT pas avoir
  changé. On sert le résultat mémorisé, préfixé d'un rappel. On économise l'appel,
  et surtout on dit à l'agent qu'il se répète.
- **Tout le reste** : on exécute normalement — relire un fichier qu'on vient d'éditer,
  relancer une commande, sont légitimes. La mémoire est alors vidée : c'est la seule
  garantie que « rien n'a changé » reste vraie.

La mémoire vit dans le `config` du run, pas dans une variable de module. Focus
fait tourner plusieurs conversations en THREADS dans un même processus : une
mémoire globale y ferait fuiter le résultat d'une conversation dans une autre.
Le `config` est en revanche partagé par tous les outils d'un même lot, y compris
ceux lancés en parallèle — c'est exactement la portée voulue.
"""
from __future__ import annotations

import json

_MEMO_KEY = "_repeat_guard_memo"

RECALL_NOTICE = (
    "[DÉJÀ JOUÉ — tu as émis cet appel à l'identique plus tôt, et rien n'a été écrit "
    "depuis : le résultat ci-dessous est le même, il n'a pas été rejoué. Si tu en "
    "attendais autre chose, ce n'est pas la répétition qui l'obtiendra — change "
    "d'approche, ou demande.]\n\n"
)


def _fingerprint(name: str, params: dict) -> str:
    """Empreinte stable d'un appel : son nom, et ses paramètres triés."""
    return name + "\x00" + json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)


def _memo(config: dict) -> dict[str, str]:
    if not isinstance(config, dict):
        return {}
    return config.setdefault(_MEMO_KEY, {})


def invalidate(config: dict) -> None:
    """Quelque chose a pu être écrit : plus rien ne garantit qu'un résultat tient."""
    _memo(config).clear()


def recall(config: dict, name: str, params: dict) -> str | None:
    """Le résultat mémorisé de cet appel exact, ou None s'il n'a jamais été joué."""
    memo = _memo(config).get(_fingerprint(name, params))
    return None if memo is None else RECALL_NOTICE + memo


def remember(config: dict, name: str, params: dict, result: str) -> None:
    _memo(config)[_fingerprint(name, params)] = result
