# [desc] Per-LLM-call breakdowns built from the on-disk turn dumps (turns.jsonl) — single source of truth, no manual replay. [/desc]
"""Builds per-LLM-call context breakdowns from the agent's payload dumps.

Reads ``~/.bouzecode/debug_payloads/<session_id>/turns.jsonl`` which contains
the *exact* messages sent to the API on each turn (with ``_cache_breakpoint``
markers and the GC state at that moment). Joining by turn number with the
session JSON's ``compaction_log`` adds the API token counts.
"""
import json
import threading
import types
from collections import OrderedDict
from pathlib import Path

from .items import (
    annotate_cache_status, annotate_system_cache_status, build_items_for_payload,
    build_tool_call_index, estimate_tokens, message_text,
)


def _load_turn_dumps(session_id: str) -> dict[int, dict]:
    """Return {turn_number: dump_record} or {} if no dump file exists.

    Le payload complet de chaque tour est une VUE : le journal ne stocke que ce qui change
    d'un appel au suivant, et `payload_dump.load_turn_map` le reconstitue (cf. l'en-tête de
    `backend/agent/payload_dump.py`). Ce module n'a donc jamais à connaître la forme du
    stockage — et `_payload_divergence` ci-dessous reste le juge du cache, inchangé."""
    if not session_id:
        return {}
    from bouzecode.backend.core.payload_view import load_turn_map
    return load_turn_map(session_id)


def _context_state_from_dump(dump: dict):
    """Adapt the dumped context_state dict into the ContextState shape we use (notes-only).

    Old dumps store the state under 'gc_state' instead of 'context_state'.
    """
    raw = dump.get("context_state") or dump.get("gc_state") or {}
    return types.SimpleNamespace(notes=raw.get("notes") or {})


def _api_tokens_for(entry: dict | None, dump: dict | None) -> dict[str, int]:
    """Return api_* token counts: compaction_log entry is authoritative; else fall
    back to the dump's token_counts (post-call record)."""
    if entry is not None:
        return {
            "api_input_tokens": entry.get("api_input_tokens", 0),
            "api_output_tokens": entry.get("api_output_tokens", 0),
            "api_cache_read": entry.get("api_cache_read", 0),
            "api_cache_create": entry.get("api_cache_create", 0),
            # Sortie estimée (message_delta jamais reçu) : la vue doit le dire.
            "api_output_estimated": bool(entry.get("api_output_estimated")),
            "api_input_estimated": bool(entry.get("api_input_estimated")),
        }
    tc = (dump or {}).get("token_counts") or {}
    return {
        "api_input_tokens": tc.get("in_tokens", 0),
        "api_output_tokens": tc.get("out_tokens", 0),
        "api_cache_read": tc.get("cache_read_tokens", 0),
        "api_cache_create": tc.get("cache_creation_tokens", 0),
        "api_output_estimated": False,
        "api_input_estimated": False,
    }


def _find_breakpoint(payload: list[dict]) -> int:
    for i, msg in enumerate(payload):
        if msg.get("_cache_breakpoint"):
            return i
    return -1


def _msg_signature(msg: dict) -> tuple:
    role = msg.get("role", "")
    content = msg.get("content", "")
    if isinstance(content, list):
        content = json.dumps(content, ensure_ascii=False, sort_keys=True)
    tcs = msg.get("tool_calls") or []
    tc_sig = json.dumps(
        [{"id": tc.get("id"), "name": tc.get("name"), "input": tc.get("input")} for tc in tcs],
        ensure_ascii=False, sort_keys=True,
    )
    return (role, content or "", msg.get("tool_call_id", ""), tc_sig)


def _payload_divergence(prev: list[dict], cur: list[dict]) -> int:
    for i in range(min(len(prev), len(cur))):
        if _msg_signature(prev[i]) != _msg_signature(cur[i]):
            return i
    return min(len(prev), len(cur))


def _summarize_items(items: list[dict]) -> tuple[dict[str, int], dict[str, int]]:
    tokens_by_status: dict[str, int] = {}
    count_by_status: dict[str, int] = {}
    for item in items:
        status = item["cache_status"]
        tokens_by_status[status] = tokens_by_status.get(status, 0) + item["est_tokens"]
        count_by_status[status] = count_by_status.get(status, 0) + 1
    return tokens_by_status, count_by_status


def _resolve_model(session_path: str, data_model: str) -> str:
    """Resolve the session model, falling back to the web-agent sidecar.

    For web agents the session file is `<agent_id>.session.json` next to a
    `<agent_id>.json` metadata file carrying the real model. CLI sessions have
    no sidecar, so the empty model is returned unchanged.
    """
    if data_model:
        return data_model
    name = Path(session_path).name
    suffix = ".session.json"
    if not name.endswith(suffix):
        return data_model
    agent_id = name[: -len(suffix)]
    sidecar = Path(session_path).parent / f"{agent_id}.json"
    if not sidecar.exists():
        return data_model
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    return meta.get("model") or data_model


def _lire_session(session_path: str) -> dict | None:
    path = Path(session_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if data.get("messages") else None


def _entete(session_path: str, data: dict, calls: list[dict]) -> dict:
    return {
        "session_id": data.get("session_id", "?"),
        "model": _resolve_model(session_path, data.get("model") or "") or "?",
        "saved_at": data.get("saved_at", "?"),
        "first_message": data.get("first_message", ""),
        "system_prompt_tokens": estimate_tokens(data.get("system_prompt", "") or ""),
        "calls": calls,
    }


_CHAMPS_API = ("api_input_tokens", "api_output_tokens", "api_cache_read", "api_cache_create",
               "api_output_estimated", "api_input_estimated")


def _appel_sans_dump(turn, timestamp, api: dict, est_tokens: int, prev_bp: int) -> dict:
    return {"turn": turn, "timestamp": timestamp, "user_prompt": "",
            **{champ: api[champ] for champ in _CHAMPS_API},
            "est_message_tokens": est_tokens, "wire_message_count": 0, "items": [],
            "tokens_by_status": {}, "count_by_status": {}, "breakpoint_payload_idx": -1,
            "prev_breakpoint_payload_idx": prev_bp, "divergence_payload_idx": -1}


class _Suivi:
    """L'état qui passe d'un appel au suivant : payload, blocs système et point de cache."""

    def __init__(self):
        self.payload: list[dict] = []
        self.system_blocks: list | None = None
        self.bp = -1


def _appel_avec_dump(turn, timestamp, api: dict, est_tokens: int, dump: dict, contexte: dict,
                     suivi: _Suivi) -> dict:
    payload = dump["messages"]
    cur_bp = _find_breakpoint(payload)
    divergence = _payload_divergence(suivi.payload, payload)
    items = build_items_for_payload(payload, contexte["system_prompt"],
                                    _context_state_from_dump(dump), contexte["tc_index"],
                                    system_blocks=dump.get("system_blocks"))
    annotate_cache_status(items, cur_bp, suivi.bp, divergence)
    annotate_system_cache_status(items, dump.get("system_blocks"), suivi.system_blocks,
                                 api["api_cache_read"])
    loop_user = next((m for m in reversed(payload) if m.get("role") == "user"), None)
    tokens_by_status, count_by_status = _summarize_items(items)
    appel = {"turn": turn, "timestamp": timestamp,
             "user_prompt": (message_text(loop_user) if loop_user else "")[:300],
             **{champ: api[champ] for champ in _CHAMPS_API},
             "est_message_tokens": est_tokens, "wire_message_count": len(payload),
             "items": items, "tokens_by_status": tokens_by_status,
             "count_by_status": count_by_status, "breakpoint_payload_idx": cur_bp,
             "prev_breakpoint_payload_idx": suivi.bp, "divergence_payload_idx": divergence}
    suivi.payload, suivi.system_blocks, suivi.bp = payload, dump.get("system_blocks"), cur_bp
    return appel


def _appel(turn, entry: dict | None, dump: dict | None, contexte: dict, suivi: _Suivi) -> dict:
    api = _api_tokens_for(entry, dump)
    timestamp = entry.get("timestamp") if entry else (dump or {}).get("timestamp")
    est_tokens = entry.get("est_message_tokens", 0) if entry else 0
    if not dump:
        return _appel_sans_dump(turn, timestamp, api, est_tokens, suivi.bp)
    return _appel_avec_dump(turn, timestamp, api, est_tokens, dump, contexte, suivi)


def _construire(session_path: str, data: dict, dumps: dict) -> dict:
    if not dumps:
        return {**_entete(session_path, data, []), "missing_dumps": True}
    log_by_turn = {e.get("turn"): e for e in data.get("compaction_log", [])
                   if e.get("event") == "llm_call"}
    contexte = {"system_prompt": data.get("system_prompt", "") or "",
                "tc_index": build_tool_call_index(data["messages"])}
    suivi = _Suivi()
    calls = [_appel(turn, log_by_turn.get(turn), dumps.get(turn), contexte, suivi)
             for turn in sorted(set(log_by_turn) | set(dumps), key=lambda t: (t is None, t))]
    return _entete(session_path, data, calls)


# ------------------------------------------------------------------ mémoire par version
#
# Construire la vue par appel coûte un décodage complet de la session ET le repli de tout le
# journal des payloads : 0,2-0,3 s sur le poste d'essai, 1,2-1,5 s pour une session de 78 Mo
# (taille courante sous Windows) — et `/turns`, `/costs`, `/turns/<n>`, `/turns/<n>/context`,
# l'enquête la refaisaient chacun, à chaque requête, `/costs?avec_sous_agents=1` une fois par
# sous-agent. Le résultat est donc mémorisé par VERSION des deux fichiers : signature
# (mtime ns, taille, inode) de la session et du journal. Une écriture de l'agent change une
# signature → reconstruction au prochain appel. Les signatures sont prises AVANT la lecture :
# une écriture concurrente laisse une entrée déjà périmée, jamais une entrée fausse.
#
# Le résultat est PARTAGÉ entre appelants : ils ne doivent pas le modifier (copier d'abord).

_MAX_EXTRAITS = 3        # une vue de session de 78 Mo retient ~140 Mo : borne serrée
_MAX_DERIVES = 2048      # vues dérivées (coûts, tableau des tours…) : quelques Ko chacune
_verrou = threading.Lock()
_extraits: "OrderedDict[str, tuple[tuple, dict]]" = OrderedDict()
_derives: "OrderedDict[tuple, object]" = OrderedDict()
_ids: dict[str, tuple[tuple, str]] = {}      # chemin → (signature de la session, session_id)


def _signature(path: Path | None) -> tuple | None:
    if path is None:
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _journal(session_id: str) -> Path | None:
    if not session_id:
        return None
    from bouzecode.backend.core.payload_view import payload_dir
    return payload_dir(session_id) / "turns.jsonl"


def _version(session_path: str) -> tuple | None:
    """(signature de la session, signature du journal), ou None si la session est absente.
    Tant que le session_id n'est pas connu pour CETTE signature de session, la partie
    journal vaut « inconnu » : la version changera une fois l'identifiant appris."""
    signature = _signature(Path(session_path))
    if signature is None:
        return None
    with _verrou:
        connu = _ids.get(session_path)
    if connu is None or connu[0] != signature:
        return (signature, "?")
    return (signature, _signature(_journal(connu[1])))


def _extraire(session_path: str) -> tuple[dict | None, dict | None, dict, tuple | None]:
    """Lecture NON mémorisée : (vue par appel, session décodée, dumps, version lue)."""
    signature = _signature(Path(session_path))
    data = _lire_session(session_path)
    if data is None:
        return None, None, {}, None
    session_id = data.get("session_id", "")
    version = (signature, _signature(_journal(session_id)))
    dumps = _load_turn_dumps(session_id)
    with _verrou:
        _ids[session_path] = (signature, session_id)
    return _construire(session_path, data, dumps), data, dumps, version


def _retenir(session_path: str, version: tuple, extrait: dict) -> None:
    with _verrou:
        _extraits[session_path] = (version, extrait)
        _extraits.move_to_end(session_path)
        while len(_extraits) > _MAX_EXTRAITS:
            _extraits.popitem(last=False)


def extract_per_call_data(session_path: str) -> dict | None:
    """Vue par appel LLM de la session, mémorisée par version (cf. ci-dessus)."""
    version = _version(session_path)
    with _verrou:
        connu = _extraits.get(session_path)
        if connu is not None and connu[0] == version:
            _extraits.move_to_end(session_path)
            return connu[1]
    extrait, _data, _dumps, version_lue = _extraire(session_path)
    if extrait is not None:
        _retenir(session_path, version_lue, extrait)
    return extrait


def extraire_avec_session(session_path: str) -> tuple[dict | None, dict | None, dict, tuple | None]:
    """Vue par appel + session décodée + dumps + version lue, en UNE lecture de chaque fichier
    (l'enquête a besoin des trois). Non mémorisé ici (l'appelant garde le sien, indexé par la
    version rendue), mais la vue par appel rejoint la mémoire commune."""
    extrait, data, dumps, version_lue = _extraire(session_path)
    if extrait is not None:
        _retenir(session_path, version_lue, extrait)
    return extrait, data, dumps, version_lue


def version_de_session(session_path: str) -> tuple | None:
    """Version courante (session, journal) SANS lire la session, telle que la rend
    `extraire_avec_session` une fois le journal identifié ; None si la session est absente."""
    return _version(session_path)


def memoriser(nom: str, session_path: str, calcul, *, depuis_extrait: bool = False):
    """Valeur dérivée de la session (et de son journal) mémorisée sous (nom, chemin, version).

    La version est relue APRÈS le calcul : si un fichier a bougé pendant, la valeur est
    rendue sans être gardée. Comme la vue par appel, la valeur est partagée : ne pas la
    modifier. `depuis_extrait` : le calcul part de `extract_per_call_data` ; si le journal de
    la session n'est pas encore identifié, la vue par appel est construite d'abord (le calcul
    la retrouvera en mémoire) pour que la valeur soit gardée dès le premier appel."""
    version = _version(session_path)
    if version is None:
        return calcul()
    if depuis_extrait and version[1] == "?":
        extract_per_call_data(session_path)
        version = _version(session_path)
    cle = (nom, session_path, version)
    with _verrou:
        if cle in _derives:
            _derives.move_to_end(cle)
            return _derives[cle]
    valeur = calcul()
    if _version(session_path) == version:
        with _verrou:
            _derives[cle] = valeur
            while len(_derives) > _MAX_DERIVES:
                _derives.popitem(last=False)
    return valeur


def oublier() -> None:
    """Vide les mémoires (tests)."""
    with _verrou:
        _extraits.clear()
        _derives.clear()
        _ids.clear()
