# [desc] Lecture unique de BOUZECODE_SERVER_PROFILE : valeurs vraies/fausses reconnues, toute autre valeur échoue FERMÉ. [/desc]
"""Le process tourne-t-il pour une application hébergée (profil serveur) ?

`BOUZECODE_SERVER_PROFILE` est lu ici et nulle part ailleurs (liste d'outils interdits,
plugins, repli TLS). Une faute de frappe ne doit pas laisser le serveur sans protection :

  - vide / absente, `0`, `false`, `no`, `non`, `off` -> inactif ;
  - `1`, `true`, `yes`, `oui`, `on` -> actif ;
  - toute autre valeur -> ACTIF (échec fermé), avec un avertissement journalisé une fois.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

SERVER_PROFILE_ENV = "BOUZECODE_SERVER_PROFILE"
_TRUE = frozenset({"1", "true", "yes", "oui", "on"})
_FALSE = frozenset({"", "0", "false", "no", "non", "off"})

_warned: set = set()


def server_profile_active() -> bool:
    """Vrai si le profil serveur est demandé ; une valeur non reconnue vaut « actif »."""
    raw = (os.environ.get(SERVER_PROFILE_ENV) or "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    if raw not in _warned:
        _warned.add(raw)
        logger.warning(
            "%s=%r non reconnu : profil serveur ACTIVÉ par sécurité (valeurs admises : "
            "1/true/yes/oui/on ou 0/false/no/non/off).", SERVER_PROFILE_ENV, raw)
    return True


def server_profile_refusal(action: str) -> str:
    """Message d'erreur explicite pour une action interdite en profil serveur."""
    return (f"{action} est interdit en profil serveur ({SERVER_PROFILE_ENV} actif) : "
            "aucun code tiers ne se charge ni ne s'installe dans le process hébergé.")
