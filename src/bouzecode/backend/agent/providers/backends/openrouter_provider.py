# [desc] Fournisseur OpenRouter épinglé : un seul fournisseur par session (cache chaud), reprises sur le même, repli sur l'ordre complet seulement ensuite, puis collage au fournisseur de repli ; chaque changement journalisé. [/desc]
"""Épinglage du fournisseur OpenRouter (rapport docs/reduction_tokens §0.3 : 26 % du non-caché
venait de ratés de cache dus au routage entre ≈ 27 fournisseurs, chacun avec son propre cache).

Réglage `openrouter_provider` de la config : `{modèle: [fournisseurs par préférence]}` ; vide
ou absent = routage libre d'OpenRouter, comme avant. Stratégie (choix de l'utilisateur,
24/09 : minimiser les changements de fournisseur, jamais de `sort` dynamique) :

1. requête épinglée : `{"order": [courant], "allow_fallbacks": false, "require_parameters": true}` ;
2. échec transitoire (429, 402, 5xx, coupure réseau) : reprises courtes sur le MÊME
   fournisseur (1, 2 puis 3 s ; un Retry-After ≤ 5 s est respecté) ;
3. seulement ensuite : `allow_fallbacks: true` sur l'ordre complet (courant en tête) ;
4. le fournisseur qui a servi (champ `provider` de la réponse) devient le courant pour la
   suite de la session — son cache est désormais chaud — et le changement est journalisé
   (`provider_switch` dans le compaction_log, visible dans /enquete).

Une session = un process d'agent : le fournisseur courant vit au niveau du module, partagé
par les appels principaux et annexes du même modèle.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# Reprises sur le fournisseur épinglé : courtes (≈ 6 s), puis repli. Un Retry-After ≤ 5 s
# annoncé par le fournisseur est respecté.
BACKOFFS_EPINGLE_S = (1.0, 2.0, 3.0)
RETRY_AFTER_MAX_S = 5.0
# 402 « in-flight » : crédit momentanément réservé par des requêtes en cours.
TRANSITOIRES = (402,)

_courant: dict[str, str] = {}


def routage(config: dict, vers_openrouter: bool) -> dict:
    """La config qui porte l'épinglage — vide hors d'OpenRouter (le gateway n'a pas de `provider`)."""
    return config if vers_openrouter else {}


def ordre(config: dict, model: str) -> list[str]:
    """Les fournisseurs préférés de `model` (id OpenRouter ou alias de la config), ou []."""
    from ..registry import resolve_provider

    for cle, liste in (config.get("openrouter_provider") or {}).items():
        if model in (cle, resolve_provider(cle)[1]) and liste:
            return list(liste)
    return []


def _slug_servi(nom: str, liste: list[str]) -> str:
    """« DeepInfra » → « deepinfra/fp8 » s'il est dans la liste, sinon le nom en minuscules."""
    bas = (nom or "").strip().lower().replace(" ", "")
    return next((s for s in liste if s.split("/")[0] == bas), bas)


def courant(model: str, liste: list[str]) -> str:
    return _courant.get(model) or liste[0]


def champ(config: dict, model: str, repli: bool = False) -> dict | None:
    """Le champ `provider` de la requête ; None si aucun épinglage n'est configuré."""
    liste = ordre(config, model)
    if not liste:
        return None
    tete = courant(model, liste)
    if repli:
        return {"order": [tete] + [s for s in liste if s != tete], "allow_fallbacks": True,
                "require_parameters": True}
    return {"order": [tete], "allow_fallbacks": False, "require_parameters": True}


def _journaliser(config: dict, model: str, de: str, vers: str, motif: str) -> None:
    logger.warning("OpenRouter %s : fournisseur %s → %s (%s)", model, de, vers, motif)
    state = config.get("_state")
    if state is not None:
        state.compaction_log.append({
            "event": "provider_switch", "timestamp": time.time(),
            "turn": getattr(state, "turn_count", 0), "model": model,
            "from": de, "to": vers, "reason": motif})


def noter_servi(config: dict, model: str, nom: str) -> None:
    """Colle la session au fournisseur qui vient de servir, s'il a changé.

    Seulement s'il est dans la liste configurée : avec `allow_fallbacks: true`, OpenRouter
    peut servir par un fournisseur HORS de l'ordre (ex. morph, exclu car sans cache) ; s'y
    coller épinglerait la session sur un fournisseur écarté. On garde alors le courant."""
    liste = ordre(config, model)
    if not liste or not nom:
        return
    servi, avant = _slug_servi(nom, liste), courant(model, liste)
    if servi not in liste:
        logger.warning("OpenRouter %s : servi par %s, hors de la liste %s — pas de collage",
                       model, servi, liste)
        return
    if servi != avant:
        _courant[model] = servi
        _journaliser(config, model, avant, servi, "repli réussi : la session reste sur lui")


def poster(post_once, payload: dict, config: dict, model: str, sleep, post_with_retry) -> object:
    """POST avec épinglage : reprises sur le même fournisseur, puis repli sur l'ordre complet.
    `post_with_retry` est celui du module appelant (couture des tests existants)."""
    from .openrouter_retry import transport_errors

    epingle = champ(config, model)
    if epingle is None:
        return post_with_retry(lambda: post_once(payload))
    payload["provider"] = epingle
    try:
        return post_with_retry(lambda: post_once(payload), sleep=sleep,
                               backoffs=BACKOFFS_EPINGLE_S, transport_backoffs=BACKOFFS_EPINGLE_S,
                               transitoires=TRANSITOIRES, retry_after_max=RETRY_AFTER_MAX_S)
    except (RuntimeError, *transport_errors()) as exc:
        payload["provider"] = champ(config, model, repli=True)
        _journaliser(config, model, epingle["order"][0], "repli sur " + ", ".join(
            payload["provider"]["order"]), f"échec persistant : {str(exc)[:120]}")
        return post_with_retry(lambda: post_once(payload), sleep=sleep)
