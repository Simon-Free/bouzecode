# [desc] API sessions: blocs (HTML ou plain pour LLM), analyse des tours, diffs, cycle de vie agent. [/desc]
"""Un seul endpoint de polling (/blocks) renvoie nouveaux blocs + statut + méta.
`?plain=1` renvoie du texte structuré (consommation par un LLM) au lieu du HTML."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ...web import pending, runner
from ..services import file_service, message_view
from ..services.sessions import analysis, costs, search, store

sessions_bp = Blueprint("sessions_api", __name__)


@sessions_bp.get("/api/sessions")
def api_sessions_list():
    return jsonify(store.list_sessions())


@sessions_bp.get("/api/sessions/grep")
def api_sessions_grep():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "paramètre 'q' (regex) obligatoire"}), 400
    day = request.args.get("day")
    model = request.args.get("model")
    role = request.args.get("role")
    limit = min(request.args.get("limit", 50, type=int), 200)
    import re as _re
    try:
        _re.compile(q)
    except _re.error as exc:
        return jsonify({"error": f"regex invalide: {exc}"}), 400
    result = search.grep_sessions(q, day=day, model=model, role=role, limit=limit)
    return jsonify(result)


def _resolve_or_404(key: str):
    ref = store.resolve(key)
    if ref is None:
        return None, (jsonify({"error": f"session inconnue: {key}"}), 404)
    return ref, None


def _plain_block(index: int, message: dict) -> dict:
    name = message.get("name", "")
    text = message_view._content_text(message)[:8000]
    kind = message_view._final_answer_kind(str(name), text)
    block: dict = {
        "idx": index,
        "role": message.get("role", ""),
        "name": name,
        "text": text,
        "tool_calls": [
            {"name": tc.get("name"), "input": tc.get("input")}
            for tc in message.get("tool_calls") or []
        ],
    }
    if kind:
        block["kind"] = kind
    return block


@sessions_bp.get("/api/sessions/<path:key>/blocks")
def api_session_blocks(key: str):
    ref, error = _resolve_or_404(key)
    if error:
        return error
    after = max(0, request.args.get("after", 0, type=int))
    plain = bool(request.args.get("plain"))
    data = store.load_session_json(ref.path)
    status = store.agent_status(ref.agent) if ref.agent else {"state": "cli"}
    if data is None:
        return jsonify({"total": 0, "blocks": [], "status": status,
                        "meta": {}, "note": "session pas encore écrite ou illisible"})
    messages = data.get("messages") or []
    if plain:
        blocks = [_plain_block(i, messages[i]) for i in range(after, len(messages))]
    else:
        blocks = [
            {"idx": i, "html": message_view.render_message(messages[i])}
            for i in range(after, len(messages))
        ]
    return jsonify({
        "total": len(messages),
        "blocks": blocks,
        "status": status,
        "meta": store.session_meta_full(data),
    })


@sessions_bp.get("/api/sessions/<path:key>/turns")
def api_session_turns(key: str):
    ref, error = _resolve_or_404(key)
    if error:
        return error
    table = analysis.turn_table(str(ref.path))
    if table is None:
        return jsonify({"calls": [], "missing_dumps": True,
                        "note": "session sans compaction_log (trop ancienne ou vide)"})
    return jsonify(table)


@sessions_bp.get("/api/sessions/<path:key>/costs")
def api_session_costs(key: str):
    ref, error = _resolve_or_404(key)
    if error:
        return error
    result = costs.session_costs(str(ref.path))
    if result is None:
        return jsonify({"models": {}, "total": None,
                        "note": "session sans compaction_log (trop ancienne ou vide)"})
    return jsonify(result)


@sessions_bp.get("/api/sessions/<path:key>/turns/<int:turn>")
def api_session_turn_detail(key: str, turn: int):
    ref, error = _resolve_or_404(key)
    if error:
        return error
    detail = analysis.turn_detail(str(ref.path), turn)
    if detail is None:
        return jsonify({"error": f"tour {turn} introuvable (dumps absents ?)"}), 404
    return jsonify(detail)


@sessions_bp.get("/api/sessions/<path:key>/files")
def api_session_files(key: str):
    ref, error = _resolve_or_404(key)
    if error:
        return error
    data = store.load_session_json(ref.path) or {}
    snapshots = data.get("file_snapshots") or {}
    diffs = file_service.render_snapshot_diffs(snapshots)
    if request.args.get("raw"):
        for diff in diffs:
            snapshot = snapshots.get(diff["path"]) or {}
            diff["before"] = snapshot.get("before") or ""
            diff["after"] = snapshot.get("after") or ""
    return jsonify({"files": diffs})


@sessions_bp.post("/api/agents/launch")
def api_agent_launch():
    payload = request.get_json(force=True) or {}
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt requis"}), 400
    cwd = payload.get("cwd") or str(file_service.ROOT)
    # Resolve typology → profile
    from ..services.typologies import get_typology
    typology_name = payload.get("typology") or ""
    typo = get_typology(typology_name, cwd) if typology_name else None
    profile = typo["profile"] if typo else ""
    paralysis = payload.get("paralysis_abort_after")
    try:
        agent = runner.create_agent(
            prompt, payload.get("model") or "", cwd,
            profile=profile,
            paralysis_abort_after=paralysis,
        )
    except runner.MissingProviderEnvError as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"key": f"agent/{agent.agent_id}", "agent_id": agent.agent_id})


@sessions_bp.post("/api/agents/<agent_id>/continue")
def api_agent_continue(agent_id: str):
    agent = runner.load_agent(agent_id)
    if agent is None:
        return jsonify({"error": "agent inconnu"}), 404
    text = ((request.get_json(force=True) or {}).get("text") or "").strip()
    if not text:
        return jsonify({"error": "texte requis"}), 400
    status = store.agent_status(agent)
    if status["state"] == "running":
        return jsonify({"error": "l'agent tourne encore — attends la fin du tour"}), 409
    if status["state"] == "awaiting_input" and pending.exists(agent.session_path):
        runner.resume_pending_agent(agent, text)
    else:
        runner.continue_agent(agent, text)
    return jsonify({"ok": True})


@sessions_bp.post("/api/agents/<agent_id>/kill")
def api_agent_kill(agent_id: str):
    agent = runner.load_agent(agent_id)
    if agent is None:
        return jsonify({"error": "agent inconnu"}), 404
    runner.kill_agent(agent)
    return jsonify({"ok": True})
