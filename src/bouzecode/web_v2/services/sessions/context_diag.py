"""Per-turn context diagnostic: what the model saw at a given turn.

For each element sent to the model this turn we expose:
  - status_label: "cache read" | "cache write" | "fresh"
  - added_at_turn: the turn at which this element FIRST entered the context.

Reuses the existing context_viewer builder (single source of truth) so the
cache-status semantics stay consistent with the historical viewer.

GOLDEN RULE: we never surface a full payload; each item's `text` is truncated
to TEXT_CAP chars.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bouzecode.web_v2.runtime.context_viewer.builder import extract_per_call_data, memoriser

TEXT_CAP = 20000

# Internal cache_status (from annotate_cache_status) -> user-facing label.
_STATUS_LABEL = {
    "cached": "cache read",
    "new-cache": "cache write",
    "fresh": "fresh",
}

# Which labels count as "delta" (added/written this turn) vs already-cached.
_DELTA_LABELS = {"fresh", "cache write"}


def _expose_item(item: dict) -> dict:
    status_label = _STATUS_LABEL.get(item.get("cache_status", "fresh"), "fresh")
    text = item.get("text") or ""
    if len(text) > TEXT_CAP:
        text = text[:TEXT_CAP] + "\n\u2026 [tronqué]"
    return {
        "kind": item.get("kind", ""),
        "label": item.get("label", ""),
        "preview": item.get("preview", ""),
        "text": text,
        "est_tokens": item.get("est_tokens", 0),
        "status_label": status_label,
        "added_at_turn": item.get("added_at_turn"),
        "payload_idx": item.get("payload_idx"),
    }


def _notes_delta_for_turn(session_path: str, turn_n: int) -> dict | None:
    timeline = memoriser("notes_timeline", session_path, lambda: _notes_timeline(session_path))
    delta = (timeline or {}).get(turn_n)
    if delta is None:
        return None
    return {
        "added": delta.get("added", []),
        "updated": delta.get("updated", []),
        "removed": delta.get("removed", []),
    }


def _notes_timeline(session_path: str) -> dict | None:
    """{tour: delta} de la PREMIÈRE entrée de chaque tour ; None si la session est illisible."""
    try:
        data = json.loads(Path(session_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    par_tour: dict = {}
    for entry in data.get("notes_timeline", []) or []:
        par_tour.setdefault(entry.get("turn"), entry.get("delta") or {})
    return par_tour


def _content_key(it: dict) -> bytes:
    """Identité d'un élément à travers les tours : son contenu brut (texte, sinon aperçu) +
    son genre — PAS payload_idx, qui est une POSITION par tour (réutilisée à chaque tour et
    None pour system/notes), donc incapable d'identifier une entrée logique.

    Rendue en empreinte (16 octets) : la table des origines est mémorisée par version de la
    session, elle ne doit pas garder une copie de chaque texte."""
    brut = f"{it.get('kind', '')}\x00{it.get('text') or it.get('preview') or ''}"
    return hashlib.blake2b(brut.encode("utf-8", "surrogatepass"), digest_size=16).digest()


def _status(it: dict) -> str:
    return _STATUS_LABEL.get(it.get("cache_status", "fresh"), "fresh")


def _origines(calls: list[dict]) -> dict[bytes, int]:
    """Le PREMIER tour où chaque contenu est entré dans le contexte."""
    origine: dict[bytes, int] = {}
    for prev in sorted(calls, key=lambda c: c.get("turn", 0)):
        if prev.get("turn") is None:
            continue
        for it in prev.get("items", []):
            origine.setdefault(_content_key(it), prev["turn"])
    return origine


def _dater(items: list[dict], origine: dict[bytes, int], turn_n: int) -> None:
    """added_at_turn : fresh / cache-write = facturé et (ré)envoyé CE tour → turn_n ;
    cache read = déjà dans le préfixe → le premier tour où ce contenu a été vu."""
    for it in items:
        it["added_at_turn"] = turn_n if _status(it) in _DELTA_LABELS \
            else origine.get(_content_key(it))


_CHAMPS_TOTAUX = ("api_input_tokens", "api_output_tokens", "api_cache_read", "api_cache_create",
                  "est_message_tokens", "wire_message_count")


def _appel_du_tour(session_path: str, turn_n: int) -> tuple[dict, dict | None]:
    data = extract_per_call_data(session_path)
    if data is None or data.get("missing_dumps"):
        return {}, None
    call = next((c for c in data.get("calls", []) if c.get("turn") == turn_n), None)
    return data, (call if call and call.get("items") else None)


def _lus_dans_le_cache(exposed: list[dict]) -> list[dict]:
    """Ce qui a VRAIMENT été lu dans le cache CE tour : les éléments du payload réel du tour
    marqués « cache read ». Ne jamais reconstruire l'historique des tours précédents : cela
    ressuscitait des éléments évincés/compactés et les marquait « cached » à tort."""
    lus = [i for i in exposed if i["status_label"] == "cache read"]
    return sorted(lus, key=lambda i: (i.get("added_at_turn") is None, i.get("added_at_turn") or 0))


def build_turn_context_diag(session_path: str, turn_n: int) -> dict | None:
    """Return the diagnostic for turn `turn_n`, or None if unavailable.

    None is returned when the session cannot be parsed or the debug payload
    dumps for the session are missing (nothing to diagnose).
    """
    data, call = _appel_du_tour(session_path, turn_n)
    if call is None:
        return None
    # Copie : la vue par appel est mémorisée et partagée (builder.memoriser).
    items = [dict(it) for it in call["items"]]
    # Relue DANS le calcul : la table est gardée sous la version courante, elle doit en venir.
    origines = memoriser(
        "origines", session_path,
        lambda: _origines((extract_per_call_data(session_path) or {}).get("calls", [])),
        depuis_extrait=True)
    _dater(items, origines, turn_n)
    exposed = [_expose_item(it) for it in items]
    return {
        "session_id": data.get("session_id", "?"),
        "model": data.get("model", "?"),
        "turn": turn_n,
        "timestamp": call.get("timestamp"),
        "totals": {champ: call.get(champ, 0) for champ in _CHAMPS_TOTAUX},
        "delta_items": [i for i in exposed if i["status_label"] in _DELTA_LABELS],
        "cached_items": _lus_dans_le_cache(exposed),
        "notes_delta": _notes_delta_for_turn(session_path, turn_n),
    }
