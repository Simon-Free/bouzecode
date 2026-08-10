# [desc] Décodage tolérant du body JSON d'une requête Flask (utf-8/BOM/latin-1) pour éviter les 400 d'encodage [/desc]
"""Lecture tolérante du corps JSON d'une requête Flask.

PowerShell (Invoke-WebRequest / curl.exe) réencode volontiers un body accentué en
latin-1 ou y ajoute un BOM, ce qui faisait planter ``request.get_json(force=True)``
avec une 400 « Failed to decode JSON object ». ``json_body`` lit les octets bruts et
tente une cascade de décodages (utf-8, utf-8-sig, latin-1) avant de parser le JSON,
si bien qu'un body mal encodé est toujours accepté au lieu d'être rejeté.
"""
from __future__ import annotations

import json
from typing import Any


def json_body(request: Any) -> dict:
    """Renvoie le body JSON de ``request`` sous forme de dict, tolérant à l'encodage.

    - Body vide → ``{}``.
    - Décodage : utf-8-sig (gère BOM + utf-8 normal), puis latin-1 (jamais d'échec).
    - JSON invalide ou non-objet (liste, scalaire) → ``{}``.
    """
    raw = request.get_data(cache=False, as_text=False) or b""
    if not raw:
        return {}
    text = None
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return {}
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
