"""Proxy LLM du portail demo_application (`<portail>/llm-proxy/anthropic|openai`).

Le proxy relaie vers le gateway IA corporate : même politique que le gateway (cache ttl 5 min par
défaut, outils natifs mesurés). Il attend des métadonnées en en-têtes HTTP, envoyées
SEULEMENT à lui (jamais à OpenRouter ni au gateway direct).

Reconnaissance : base URL contenant `/llm-proxy/`, ou BOUZECODE_LLM_PROXY=1 (proxy monté
sous un autre chemin). Module sans dépendance : importé par registry et les backends.
"""
from __future__ import annotations

import os

PROXY_PATH_MARKER = "/llm-proxy/"
SOURCE = "bouzecode"
COMMENT_MAX = 200


def is_llm_proxy(base_url: str | None) -> bool:
    if os.environ.get("BOUZECODE_LLM_PROXY", "") == "1":
        return bool(base_url)
    return bool(base_url) and PROXY_PATH_MARKER in (base_url.rstrip("/") + "/")


def _ascii(text: str) -> str:
    """Les valeurs d'en-tête HTTP doivent rester ASCII imprimable (httpx/requests)."""
    cleaned = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in text)
    return cleaned.strip()


def _comment(config: dict) -> str:
    explicit = os.environ.get("BOUZECODE_LLM_PROXY_COMMENT")
    if explicit:
        return _ascii(explicit)[:COMMENT_MAX]
    parts = [os.path.basename(os.path.normpath(os.getcwd()))]
    agent = (config.get("_agent_name") or os.environ.get("BOUZECODE_TICKET_SLUG")
             or os.environ.get("BOUZECODE_TICKET_ID") or "")
    if agent:
        parts.append(str(agent))
    return _ascii(" / ".join(p for p in parts if p))[:COMMENT_MAX]


def proxy_headers(base_url: str | None, config: dict | None) -> dict[str, str]:
    """En-têtes X-Demo-* pour une requête vers `base_url` ; {} hors proxy."""
    if not is_llm_proxy(base_url):
        return {}
    config = config or {}
    headers = {"X-Demo-Source": SOURCE}
    session = _ascii(str(config.get("_session_id") or ""))
    if session:
        headers["X-Demo-Session"] = session
    comment = _comment(config)
    if comment:
        headers["X-Demo-Comment"] = comment
    return headers
