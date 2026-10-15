# [desc] Choix du modèle d'un appel annexe (résumé, compaction, juge) : même fournisseur que la session. [/desc]
"""Le modèle d'un APPEL ANNEXE (résumé de réflexion, juge et synthèse de compaction…).

Un appel annexe partait sur un modèle Anthropic figé (littéral ou ``DEFAULTS["model"]``
du CODE, résolu à l'import) : sur une session OpenRouter sans clé Anthropic, il échouait
en 401 à chaque tour — la note de travail n'était plus compactée et a grossi jusqu'à
393 000 caractères, relus à chaque tour (constaté le 2026-09-24 sur DeepSeek).

Règle unique (choix de l'utilisateur, 2026-09-24) : le modèle est choisi UNE fois, dans la
config, et sert à TOUT — agents, sous-agents et appels annexes. Résolu à l'appel (jamais à
l'import, qui ignorait la config). Le défaut du code ne sert que si la config n'a pas de modèle.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_deja_signales: set[tuple[str, str]] = set()


def modele_annexe(config: dict | None) -> str:
    """Le modèle de la session : un seul choix de modèle pour tout."""
    session = str((config or {}).get("model") or "")
    if session:
        return session
    from ...core.config import DEFAULTS
    return str(DEFAULTS["model"])


def _fournisseur(model: str) -> str:
    from .registry import resolve_provider
    return resolve_provider(model)[0]


def echec_d_authentification(exc: BaseException) -> bool:
    """401 / clé absente : réessayer au tour suivant échouera de la même façon."""
    texte = f"{type(exc).__name__} {exc}"
    return "AuthenticationError" in texte or "401" in texte or "Missing Authentication" in texte


def signaler_echec(nom: str, model: str, exc: BaseException) -> None:
    """Journalise l'échec d'un appel annexe ; un échec d'authentification ne l'est qu'UNE fois."""
    if not echec_d_authentification(exc):
        log.warning("appel annexe %s : échec (%s)", nom, exc)
        return
    cle = (nom, _fournisseur(model) if model else "?")
    if cle in _deja_signales:
        return
    _deja_signales.add(cle)
    log.warning("appel annexe %s : fournisseur %s sans clé valide (modèle %s) — l'appel est "
                "sauté pour cette session ; vérifie la clé du fournisseur de ton modèle.", nom, cle[1], model)
