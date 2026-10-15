# [desc] GET /api/sessions/<key>/blocks : l'unique endpoint de polling du fil (blocs HTML ou texte, statut, file de messages, méta), ETag/304 tant que rien ne bouge. LECTURE PURE. [/desc]
"""Une lecture PURE (spec ticketing B1, critère 1) : la file de messages d'un agent est LUE ici,
jamais livrée — la livraison relève du watchdog (`wake.tick` → `file_messages.livrer_prets`)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from flask import jsonify, make_response, request

from ...services.sessions import store
from ...services.work import file_messages, subagent_events
from . import sessions_bp
from ._commun import session_ou_404
from .blocs_rendu import (LAUNCHING_PREFIX, bloc_texte, blocs_html, blocs_de_lancement,
                          code_perime, statut_avec_vivacite)


def _plage(total: int) -> tuple[int, int]:
    """`tail=N` au chargement initial (`after=0`) : seulement les N derniers messages ; la réponse
    dit où la page commence (`debut`) et le fil demande les précédents par `after`+`before`.
    Sans `tail` ni `before`, réponse complète (autres consommateurs de /blocks)."""
    after = max(0, request.args.get("after", 0, type=int))
    before = request.args.get("before", type=int)
    tail = request.args.get("tail", type=int)
    fin = total if before is None else max(after, min(before, total))
    debut = min(after, fin)
    if tail and tail > 0 and after == 0 and before is None:
        debut = max(0, total - tail)
    return debut, fin


def _marqueurs_demandes(agent) -> bool:
    return (agent is not None and not request.args.get("plain")
            and (request.args.get("after", 0, type=int) <= 0
                 or request.args.get("before") is not None))


def _etag_des_blocs(path, status: dict, queue: list, events: list) -> str | None:
    """Empreinte de la réponse, calculée SANS décoder la session : version du fichier,
    paramètres, statut, file d'attente et marqueurs de sous-agents. Le fil poll /blocks toutes
    les 1,5 s ; tant que rien n'a bougé, il reçoit un 304 au lieu d'un décodage complet."""
    try:
        st = Path(path).stat()
    except OSError:
        return None
    base = json.dumps([st.st_mtime_ns, st.st_size, st.st_ino, sorted(request.args.items(multi=True)),
                       status, queue, events], sort_keys=True, default=str)
    return hashlib.blake2b(base.encode("utf-8"), digest_size=16).hexdigest()


@sessions_bp.get("/api/sessions/<path:key>/blocks")
def api_session_blocks(key: str):
    """?after=N&before=&tail=&plain=1 — conversation : {total, debut, blocks, status, queue, meta}
    ; plain=1 → texte structuré sans HTML. Clé `launching/<ticket>` : la phase du lancement.
    ETag : 304 tant que rien n'a bougé. 404 `session_inconnue`."""
    if key.startswith(LAUNCHING_PREFIX):
        return blocs_de_lancement(key[len(LAUNCHING_PREFIX):])
    ref = session_ou_404(key)
    status = statut_avec_vivacite(ref.agent)
    queue = file_messages.lister(ref.agent.agent_id) if ref.agent is not None else []
    events = subagent_events.build_events(ref.agent) if _marqueurs_demandes(ref.agent) else []
    etag = _etag_des_blocs(ref.path, status, queue, events)
    if etag is not None and request.if_none_match.contains_weak(etag):
        resp = make_response("", 304)
    else:
        resp = _reponse_des_blocs(key, ref, status, queue, events)
    if etag is not None and resp.status_code in (200, 304):
        resp.set_etag(etag)
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def _reponse_des_blocs(key: str, ref, status: dict, queue: list, events: list):
    data = store.load_session_json(ref.path)
    if data is None:
        return jsonify({"total": 0, "blocks": [], "status": status, "queue": queue,
                        "meta": {}, "note": "session pas encore écrite ou illisible"})
    messages = data.get("messages") or []
    plage = _plage(len(messages))
    if request.args.get("plain"):
        blocks = [bloc_texte(i, messages[i]) for i in range(*plage)]
    else:
        blocks = blocs_html(key, ref.path, messages, plage, events)
    return jsonify({"total": len(messages), "debut": plage[0], "blocks": blocks,
                    "status": status, "queue": queue,
                    "meta": {**store.session_meta_full(data), **code_perime(data)}})
