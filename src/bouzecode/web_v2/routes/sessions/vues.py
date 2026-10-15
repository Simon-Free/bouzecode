# [desc] Vues lisibles d'une session : supervision (overview), texte partiel du tour en cours (streaming), récap structuré (ou agrégé des sous-agents), diffs des fichiers modifiés. LECTURE PURE. [/desc]
from __future__ import annotations

import json
import time
from pathlib import Path

from flask import jsonify, request

from ...runtime.runner import agent_registre
from ...runtime.context_viewer.builder import memoriser
from ...services import file_service, recap_service
from ...services.erreurs import Refus
from ...services.sessions import overview, store
from ...services.work.taches_vue import related_files_de_session
from ....backend.agent.related_files import avec_existence
from . import sessions_bp
from ._commun import donnees_ou_404, json_ou_texte, session_ou_404


@sessions_bp.get("/api/sessions/<path:key>/overview")
def api_session_overview(key: str):
    """vue supervision courante: résumé session + derniers tours (paginé ?after=N&limit=30). Texte
    plain par défaut, ?json pour JSON structuré."""
    data = donnees_ou_404(session_ou_404(key))
    result = overview.build_overview(data, key, after=request.args.get("after", 0, type=int),
                                     limit=request.args.get("limit", 30, type=int))
    return json_ou_texte(result, lambda r: overview.format_plain(r, key))


@sessions_bp.get("/api/sessions/<path:key>/partial")
def api_session_partial(key: str):
    """Texte partiel du tour en cours (streaming) : {turn, seq, phase, text, thinking} pendant
    qu'un message se produit, {text: null} sinon. Lit `<session>.partial.json`, écrit par le
    runner (`backend.agent.partial_stream.write_partial`) à chaque `TextChunk`."""
    partial_path = session_ou_404(key).path.with_suffix(".partial.json")
    for attempt in range(2):
        try:
            data = json.loads(partial_path.read_text(encoding="utf-8"))
            return jsonify({"turn": data.get("turn"), "seq": data.get("seq"),
                            "phase": data.get("phase", "text"), "text": data.get("text"),
                            "thinking": data.get("thinking", "")})
        except FileNotFoundError:
            return jsonify({"text": None})
        except (OSError, json.JSONDecodeError):
            if attempt == 0:
                time.sleep(0.03)  # écriture concurrente : une seconde lecture suffit
    return jsonify({"text": None})


def _version_du_recap(path) -> str:
    """mtime de la session : change quand l'agent produit un nouveau récap (cache front)."""
    try:
        return str(Path(path).stat().st_mtime)
    except OSError:
        return ""


def _recap_agrege(ref, version: str):
    """Manager sans récap propre : les récaps de ses sous-agents, concaténés sans LLM."""
    if ref.kind != "agent" or ref.agent is None:
        return None
    children = recap_service.aggregate_children_recaps(
        ref.agent.agent_id, agent_registre.list_agents(), lambda p: store.load_session_json(Path(p)))
    if not children:
        return None
    return jsonify({"recap": None, "recap_missing": False, "recap_version": version,
                    "is_aggregate": True, "children": children, "diffs": []})


def _resume_du_recap(path) -> dict | None:
    """Ce que la route du récap lit dans la session, mémorisé par version du fichier (une
    session de 78 Mo coûtait 0,5 s de décodage à chaque ouverture de l'onglet)."""
    data = store.load_session_json(path)
    if data is None:
        return None
    recap = data.get("recap")
    recap = recap if isinstance(recap, dict) and recap else None
    return {"recap": recap, "recap_missing": bool(data.get("recap_missing")),
            "diffs": recap_service.session_recap_diffs(recap, data),
            "related_files": related_files_de_session(data)}


@sessions_bp.get("/api/sessions/<path:key>/recap")
def api_session_recap(key: str):
    """Récap structuré (symptômes / explication / tests / changements) posé par la clôture
    FinalAnswer → {recap, recap_missing, recap_version, diffs} ; un manager sans récap rend ceux
    de ses sous-agents (`is_aggregate`). Une session morte sans récap rend un remplaçant (200),
    pas un 404. 404 `session_introuvable` (details.recap_missing) si la session n'existe pas."""
    ref = store.resolve(key)
    resume = memoriser("recap_session", str(ref.path), lambda: _resume_du_recap(ref.path)) \
        if ref is not None else None
    if resume is None:
        raise Refus("session_introuvable", "session inconnue, pas encore écrite ou illisible",
                    404, recap_missing=True)
    version = _version_du_recap(ref.path)
    #  Existence relue à CHAQUE appel (le résumé est mémorisé, le disque bouge).
    fichiers = avec_existence(resume.get("related_files") or [])
    if resume["recap"] is not None or fichiers:
        return jsonify({"recap": resume["recap"], "recap_missing": resume["recap_missing"],
                        "recap_version": version, "diffs": resume["diffs"],
                        "related_files": fichiers})
    return _recap_agrege(ref, version) or jsonify({
        "recap": None, "recap_missing": True, "note": "session interrompue, récap indisponible",
        "recap_version": version, "diffs": resume["diffs"], "related_files": []})


@sessions_bp.get("/api/sessions/<path:key>/files")
def api_session_files(key: str):
    """diffs des fichiers modifiés (file_snapshots) → {files:[{path, is_new, added, html}]}. ?raw=1
    joint `before`/`after` bruts (Monaco côte-à-côte)."""
    data = store.load_session_json(session_ou_404(key).path) or {}
    snapshots = data.get("file_snapshots") or {}
    diffs = file_service.render_snapshot_diffs(snapshots)
    if request.args.get("raw"):
        for diff in diffs:
            snapshot = snapshots.get(diff["path"]) or {}
            diff["before"] = snapshot.get("before") or ""
            diff["after"] = snapshot.get("after") or ""
    return jsonify({"files": diffs})
