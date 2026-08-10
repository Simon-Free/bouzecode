# [desc] Sonde réseau de l'API ANTHROPIC (ping avec retries) et rédaction du verdict env/joignabilité, sans état. [/desc]
"""Partie SANS ÉTAT du sanity-check API (l'état et les gardes vivent dans api_sanity).

Une seule règle de lecture : n'importe quel statut HTTP prouve que le chemin réseau est
up ; seule une erreur de connexion (DNS, proxy, timeout, refused) vaut KO — et seulement
après plusieurs tentatives, parce qu'un hoquet à froid au boot n'est pas une panne.
"""
from __future__ import annotations

import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 8.0
# Pauses entre tentatives ; la dernière valeur est réutilisée si attempts > len().
BACKOFF_S = (0.5, 1.5)

# Clés qui valent « une credential anthropic est présente ».
KEY_ENVS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def default_ping(base_url: str, timeout: float = DEFAULT_TIMEOUT_S) -> bool:
    """Sonde de joignabilité. Tout statut HTTP (200/401/404…) → réseau up → True.
    Échec de connexion → False. Ne lève jamais."""
    try:
        req = urllib.request.Request(base_url, method="GET")
        urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — URL de passerelle configurée
        return True
    except urllib.error.HTTPError:
        # Le serveur a répondu (auth/route) → le chemin réseau est joignable.
        return True
    except Exception:  # noqa: BLE001 — URLError/timeout/socket/proxy = injoignable
        return False


def reachable(base_url: str, probe, attempts: int, sleep) -> bool:
    """`attempts` tentatives espacées par un backoff. Une sonde qui LÈVE compte comme
    une tentative ratée (jamais de crash) — c'est exactement le cas proxy/DNS."""
    for attempt in range(attempts):
        try:
            if probe(base_url):
                return True
        except Exception:  # noqa: BLE001 — une sonde cassée ne doit jamais remonter
            logger.warning("[api-sanity] sonde en erreur (%d/%d)", attempt + 1, attempts)
        if attempt + 1 < attempts:
            sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
    return False


def verdict(env_source, probe, attempts: int, sleep) -> tuple[bool, str, bool, bool]:
    """(ok, detail, base_url_present, key_present).

    Les deux détails KO sont volontairement distincts : « env absente » est un problème
    de LANCEMENT (redémarrer via bouzeui.ps1 est le remède), « injoignable » est un
    problème de RÉSEAU (redémarrer n'y change rien, il faut re-sonder).
    """
    base_url = (env_source.get("ANTHROPIC_BASE_URL") or "").strip()
    key_present = any((env_source.get(k) or "").strip() for k in KEY_ENVS)

    if not base_url or not key_present:
        missing = []
        if not base_url:
            missing.append("ANTHROPIC_BASE_URL")
        if not key_present:
            missing.append("ANTHROPIC_API_KEY")
        detail = (
            "variables d'environnement API absentes: " + ", ".join(missing)
            + " — le serveur a probablement été relancé hors bouzeui.ps1 ; "
            "relance-le via bouzeui.ps1 (revérifier ne suffira pas)"
        )
        return False, detail, bool(base_url), bool(key_present)

    if reachable(base_url, probe, attempts, sleep):
        return True, "env API OK (base_url joignable)", True, True

    detail = (
        f"ANTHROPIC_BASE_URL={base_url} injoignable après {attempts} tentative(s) "
        "(proxy/DNS/timeout) — l'env est correcte, c'est le réseau : clique "
        "« Revérifier » quand il est revenu, inutile de redémarrer"
    )
    return False, detail, True, True
