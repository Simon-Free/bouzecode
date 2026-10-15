# [desc] Verdict env API du fournisseur du modèle configuré (retries au boot + re-sonde à chaud) qui garde les spawns et alimente le bandeau UI. [/desc]
"""Verdict « les agents peuvent-ils parler au provider ? ».

Le verdict n'est plus figé à vie : un faux négatif transitoire au boot (hoquet DNS/proxy
à froid) se répare tout seul. Deux mécanismes, dans cet ordre :
  1. au boot, plusieurs tentatives espacées avant de conclure KO ;
  2. après un KO, re-sonde paresseuse (cooldown) déclenchée par toute lecture d'état ou
     toute demande de spawn, plus un POST /api/env-sanity/recheck explicite.
Un verdict OK ne coûte jamais une seule sonde. La sonde elle-même vit dans api_probe.
"""
from __future__ import annotations

import functools
import logging
import os
import threading
import time

from . import api_probe

logger = logging.getLogger(__name__)

# Dernier verdict connu. None = jamais capturé (sentinelle d'idempotence).
BOOT_API_OK: bool | None = None
BOOT_API_DETAIL: str = ""
BOOT_BASE_URL_PRESENT: bool = False
BOOT_KEY_PRESENT: bool = False
BOOT_PROVIDER: str = "anthropic"
LAST_CHECK_AT: float = 0.0

# Boot : plusieurs tentatives, timeout large. Une sonde unique à 3 s suffisait à geler
# un KO mensonger pour toute la vie du process alors que le gateway répond en 0,4 s.
BOOT_ATTEMPTS = 3
BOOT_TIMEOUT_S = api_probe.DEFAULT_TIMEOUT_S
# Re-sonde : UNE tentative courte, pour ne jamais faire traîner un GET ou un spawn.
RECHECK_ATTEMPTS = 1
RECHECK_TIMEOUT_S = 4.0
RECHECK_COOLDOWN_S = 20.0

# Messages 503 distincts : l'action utile n'est pas la même dans les deux cas.
SPAWN_REFUSED_MESSAGE = "env API KO — redémarre via bouzeui.ps1"
SPAWN_REFUSED_UNREACHABLE = (
    "API injoignable — réseau/proxy, pas l'env : réessaie ou clique « Revérifier » "
    "(redémarrer ne sert à rien)"
)

# Injections retenues du dernier capture_api_sanity(env=, ping=, sleep=) : la re-sonde
# rejoue EXACTEMENT la même source d'env et la même sonde. C'est le seam de test.
_ENV_SOURCE: dict | None = None
_PING = None
_SLEEP = None
_MODEL: str | None = None
_LOCK = threading.Lock()


def _modele() -> str:
    """Le modèle par défaut des agents : injecté (tests), sinon ~/.bouzecode/config.json.
    Sous injection d'env sans modèle, le défaut du code : le test ne dépend pas du poste."""
    from ..backend.core import config as core_config
    if _MODEL:
        return _MODEL
    defaut = str(core_config.DEFAULTS.get("model") or "")
    if _ENV_SOURCE is not None or not core_config.CONFIG_FILE.exists():
        return defaut
    try:
        import json
        return str(json.loads(core_config.CONFIG_FILE.read_text(encoding="utf-8")).get("model")
                   or defaut)
    except (OSError, ValueError):
        return defaut


def _fournisseur() -> str:
    from ..backend.agent.providers.registry import resolve_provider
    return resolve_provider(_modele())[0]


def _evaluate(*, attempts: int, timeout: float, label: str) -> None:
    """Recalcule le verdict et le stocke. Fail-safe : ne lève jamais."""
    global BOOT_API_OK, BOOT_API_DETAIL, BOOT_BASE_URL_PRESENT, BOOT_KEY_PRESENT
    global LAST_CHECK_AT, BOOT_PROVIDER
    try:
        env_source = _ENV_SOURCE if _ENV_SOURCE is not None else os.environ
        probe = _PING or functools.partial(api_probe.default_ping, timeout=timeout)
        sleep = _SLEEP or time.sleep
        BOOT_PROVIDER = _fournisseur()
        ok, detail, base_present, key_present = api_probe.verdict(
            env_source, probe, attempts, sleep, provider=BOOT_PROVIDER
        )
    except Exception:  # noqa: BLE001 — le sanity-check ne doit jamais casser le boot
        logger.exception("[api-sanity] évaluation en échec — verdict prudent KO")
        ok, detail = False, "sanity-check API en échec interne"
        base_present = key_present = False

    BOOT_API_OK, BOOT_API_DETAIL = ok, detail
    BOOT_BASE_URL_PRESENT, BOOT_KEY_PRESENT = base_present, key_present
    LAST_CHECK_AT = time.monotonic()
    (logger.info if ok else logger.error)("[api-sanity] %s: %s", label, detail)


def capture_api_sanity(*, env: dict | None = None, ping=None, sleep=None,
                       model: str | None = None) -> None:
    """Capture le verdict au boot. Idempotent par défaut (ne re-sonde pas si déjà
    capturé) pour qu'un double create_app en test ne touche pas le réseau.
    Passer `env`/`ping` FORCE une re-capture (injection de dépendance, PAS du mock) :
    les tests pilotent l'env et la joignabilité exactes, et `sleep` neutralise le
    backoff. Ces injections sont mémorisées et rejouées par la re-sonde."""
    global _ENV_SOURCE, _PING, _SLEEP, _MODEL
    forced = env is not None or ping is not None or model is not None
    if BOOT_API_OK is not None and not forced:
        return
    _ENV_SOURCE, _PING, _SLEEP, _MODEL = env, ping, sleep, model
    _evaluate(attempts=BOOT_ATTEMPTS, timeout=BOOT_TIMEOUT_S, label="boot")


def recheck_api_sanity() -> dict:
    """Re-sonde MAINTENANT (une tentative courte) et renvoie l'état à jour. C'est ce
    qui supprime le besoin de redémarrer après un faux négatif transitoire."""
    with _LOCK:
        _evaluate(attempts=RECHECK_ATTEMPTS, timeout=RECHECK_TIMEOUT_S, label="re-sonde")
    return _state()


def _recheck_due() -> bool:
    if BOOT_API_OK is None or BOOT_API_OK:
        return False
    return (time.monotonic() - LAST_CHECK_AT) >= RECHECK_COOLDOWN_S


def _maybe_recheck() -> None:
    """Re-sonde paresseuse quand le dernier verdict est KO et que le cooldown est
    écoulé. Un verdict OK (ou jamais capturé) ne coûte aucune sonde."""
    if not _recheck_due():
        return
    with _LOCK:
        if not _recheck_due():  # un autre thread vient peut-être de le faire
            return
        _evaluate(attempts=RECHECK_ATTEMPTS, timeout=RECHECK_TIMEOUT_S, label="re-sonde auto")


def _state() -> dict:
    return {
        "ok": bool(BOOT_API_OK),
        "detail": BOOT_API_DETAIL,
        "base_url_present": BOOT_BASE_URL_PRESENT,
        "key_present": BOOT_KEY_PRESENT,
        # env_missing distingue « mauvais lancement » (redémarrer) de « réseau » (revérifier).
        "env_missing": not (BOOT_BASE_URL_PRESENT and BOOT_KEY_PRESENT),
        "provider": BOOT_PROVIDER,
        "provider_label": api_probe.exigence(BOOT_PROVIDER)["nom"],
    }


def api_sanity_state() -> dict:
    """État consommé par GET /api/env-sanity et les gardes. Déclenche au passage la
    re-sonde paresseuse : le bandeau rouge tombe tout seul dès que le réseau revient."""
    _maybe_recheck()
    return _state()


def reset_api_sanity() -> None:
    """Remet le module à « jamais capturé » (utilisé par les tests entre scénarios)."""
    global BOOT_API_OK, BOOT_API_DETAIL, BOOT_BASE_URL_PRESENT, BOOT_KEY_PRESENT
    global LAST_CHECK_AT, _ENV_SOURCE, _PING, _SLEEP, _MODEL, BOOT_PROVIDER
    BOOT_API_OK, BOOT_API_DETAIL = None, ""
    BOOT_PROVIDER, _MODEL = "anthropic", None
    BOOT_BASE_URL_PRESENT = BOOT_KEY_PRESENT = False
    LAST_CHECK_AT = 0.0
    _ENV_SOURCE = _PING = _SLEEP = None


def require_api_sanity():
    """Garde des spawns : le refus 503 `env_indisponible` (`services.erreurs.Refus`) quand l'env
    API est KO, None quand le spawn est autorisé. Re-sonde d'abord si le KO est vieux — un réseau
    revenu débloque les spawns SANS redémarrage. Rien de Flask : la route sérialise."""
    _maybe_recheck()
    if BOOT_API_OK:
        return None
    from .services.erreurs import Refus

    env_missing = not (BOOT_BASE_URL_PRESENT and BOOT_KEY_PRESENT)
    message = SPAWN_REFUSED_MESSAGE if env_missing else SPAWN_REFUSED_UNREACHABLE
    if env_missing and BOOT_PROVIDER != "anthropic":
        nom = api_probe.exigence(BOOT_PROVIDER)["nom"]
        message = f"configuration {nom} incomplète — complète l'environnement puis redémarre"
    return Refus("env_indisponible", message, 503, detail=BOOT_API_DETAIL,
                 env_missing=env_missing)
