# [desc] Sonde réseau du fournisseur LLM du modèle configuré (ping avec retries) et verdict env/joignabilité, sans état. [/desc]
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


def default_ping(base_url: str, timeout: float = DEFAULT_TIMEOUT_S) -> bool:
    """Sonde de joignabilité. Tout statut HTTP (200/401/404…) → réseau up → True.
    Échec de connexion → False. Ne lève jamais."""
    try:
        req = urllib.request.Request(base_url, method="GET")
        urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — URL gateway interne
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


def exigence(provider: str) -> dict:
    """Ce que le fournisseur exige pour qu'un agent puisse lui parler : l'URL (variable d'env
    OU constante publique) et au moins une des variables de clé.

    Lu dans registry.PROVIDERS, source unique : une copie locale avait déjà divergé (clé
    gateway prod, URL OpenRouter redéclarée). Un fournisseur inconnu retombe sur Anthropic.
    """
    from ..backend.agent.providers.registry import PROVIDERS
    prov = PROVIDERS.get(provider) or PROVIDERS["anthropic"]
    url_env = prov.get("base_url_env") or ""
    return {"nom": prov["label"], "url_env": url_env,
            "url": "" if url_env else (prov.get("base_url") or ""),
            "cles": tuple(prov["key_envs"])}


def _manquants(env_source, exig: dict) -> tuple[str, bool, list[str]]:
    base_url = (env_source.get(exig["url_env"]) or "").strip() if exig["url_env"] else exig["url"]
    key_present = any((env_source.get(k) or "").strip() for k in exig["cles"])
    missing = ([] if base_url else [exig["url_env"]]) + ([] if key_present else [exig["cles"][0]])
    return base_url, key_present, missing


def _detail_env_absente(provider: str, exig: dict, missing: list[str]) -> str:
    if provider == "anthropic":
        return ("variables d'environnement API absentes: " + ", ".join(missing)
                + " — le serveur a probablement été relancé hors bouzeui.ps1 ; "
                "relance-le via bouzeui.ps1 (revérifier ne suffira pas)")
    return (f"configuration {exig['nom']} incomplète : " + ", ".join(missing)
            + " absente(s) — ajoute-la(les) à l'environnement du serveur puis redémarre-le "
            "(revérifier ne suffira pas)")


def verdict(env_source, probe, attempts: int, sleep,
            provider: str = "anthropic") -> tuple[bool, str, bool, bool]:
    """(ok, detail, base_url_present, key_present) pour le fournisseur `provider`.

    Les deux détails KO sont volontairement distincts : « env absente » est un problème
    de LANCEMENT (redémarrer est le remède), « injoignable » est un problème de RÉSEAU
    (redémarrer n'y change rien, il faut re-sonder).
    """
    exig = exigence(provider)
    base_url, key_present, missing = _manquants(env_source, exig)
    if missing:
        return False, _detail_env_absente(provider, exig, missing), bool(base_url), key_present
    if reachable(base_url, probe, attempts, sleep):
        return True, f"env API OK ({exig['nom']} joignable)" if provider != "anthropic" \
            else "env API OK (base_url joignable)", True, True
    nom_url = f"{exig['url_env']}={base_url}" if exig["url_env"] else f"{exig['nom']} ({base_url})"
    detail = (
        f"{nom_url} injoignable après {attempts} tentative(s) "
        "(proxy/DNS/timeout) — l'env est correcte, c'est le réseau : clique "
        "« Revérifier » quand il est revenu, inutile de redémarrer"
    )
    return False, detail, True, True
