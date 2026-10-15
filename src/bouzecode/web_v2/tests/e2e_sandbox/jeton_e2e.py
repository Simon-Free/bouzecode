# [desc] Jeton local d'un serveur de bac à sable, lu dans la page servie (meta bouzecode-token) : à joindre aux mutations des E2E. [/desc]
"""Les mutations `/api/` exigent `X-Bouzecode-Token` (web_v2/securite.py). Le bac à sable tourne
avec SON HOME : son jeton n'est pas celui de `~/.bouzecode/web_v2/token` du poste. On le lit là
où le front le lit, dans `<meta name="bouzecode-token">` d'une page du serveur visé.
"""
from __future__ import annotations

import functools
import re
import urllib.request

EN_TETE = "X-Bouzecode-Token"
_META = re.compile(r'<meta name="bouzecode-token" content="([^"]*)"')


@functools.lru_cache(maxsize=None)
def jeton_du_serveur(base: str) -> str:
    #  Boucle locale : jamais par le proxy d'entreprise (cf. backend/core/local_http.py).
    ouvreur = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with ouvreur.open(f"{base.rstrip('/')}/", timeout=20) as r:
        page = r.read().decode("utf-8", errors="replace")
    trouve = _META.search(page)
    if not trouve or not trouve.group(1):
        raise RuntimeError(f"{base} ne sert pas de jeton dans <meta name=\"bouzecode-token\">")
    return trouve.group(1)


def en_tetes(base: str, method: str) -> dict[str, str]:
    """L'en-tête du jeton pour une mutation ({} pour GET/HEAD, qui n'en ont pas besoin)."""
    if method.upper() in ("GET", "HEAD"):
        return {}
    return {EN_TETE: jeton_du_serveur(base)}
