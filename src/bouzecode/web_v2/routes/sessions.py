# [desc] API sessions: blocs (HTML ou plain pour LLM), analyse des tours, diffs, cycle de vie agent. [/desc]
"""Un seul endpoint de polling (/blocks) renvoie nouveaux blocs + statut + méta.
`?plain=1` renvoie du texte structuré (consommation par un LLM) au lieu du HTML."""
from __future__ import annotations

import time
from pathlib import Path

from flask import Blueprint, jsonify, make_response, request, send_file

from ._body import json_body
from ..runtime import pending, runner
from ..services import file_service, message_view, recap_service
from ..services.sessions import (analysis, costs, listing_cache, overview, purge, recovery,
                                 search, store)
from ..services.work import (awaiting, delivery, dispatch, launch_phase, liveness,
                             subagent_events, tickets)
from ..services.work.tickets import _find_verdict

sessions_bp = Blueprint("sessions_api", __name__)

_INTERRUPT_REFUSED = (
    "⛔ Interruption REFUSÉE par l'OS pour l'agent `{agent_id}` : {error}. Le process est "
    "peut-être déjà en train de mourir, ou son pid appartient à une autre session. L'agent "
    "n'a PAS été arrêté — réessaie, ou vérifie son process avant de relancer le ticket."
)


@sessions_bp.get("/api/sessions")
def api_sessions_list():
    include_tests = request.args.get("include_tests") in ("1", "true", "yes")
    return jsonify(listing_cache.cached_list_sessions(include_tests=include_tests))


@sessions_bp.get("/api/sessions/<path:key>/download")
def api_session_download(key: str):
    """Télécharge le JSON brut de la session (agent/<id> ou daily/<date>/<file>)."""
    ref = store.resolve(key)
    if ref is None or not ref.path.is_file():
        return jsonify({"error": "session introuvable"}), 404
    return send_file(ref.path, as_attachment=True, download_name=ref.path.name,
                     mimetype="application/json")


@sessions_bp.get("/api/conversations/interrupted")
def api_conversations_interrupted():
    return jsonify({"conversations": recovery.list_interrupted()})


@sessions_bp.get("/api/agents/awaiting")
def api_agents_awaiting():
    """Les agents qui attendent une réponse de l'utilisateur, AVEC leur question.

    La liste à regarder pour savoir sur qui on bloque : chaque entrée porte le texte de
    la question, ses options, si la réponse peut être libre, depuis quand elle attend, et
    où répondre (projet/ticket). Aucun log à lire, aucun état à recouper à la main."""
    return jsonify({"agents": awaiting.agents_awaiting_answer()})


@sessions_bp.get("/api/agents/unreachable")
def api_agents_unreachable():
    """Les tickets ouverts dont l'agent est INTROUVABLE (enregistrement disparu du parc).

    Un trou nommé plutôt qu'un trou tout court : sans cette liste, un agent injoignable
    ne se manifestait que par des envois qui échouent et un ticket qui semble planté."""
    return jsonify({"tickets": awaiting.unreachable_ticket_agents()})


@sessions_bp.get("/api/conversations/test-candidates")
def api_conversations_test_candidates():
    """Aperçu des conversations de test (heuristique titre/prompt), NON running."""
    return jsonify({"candidates": purge.list_test_candidates()})


@sessions_bp.post("/api/conversations/purge-tests")
def api_conversations_purge_tests():
    """Soft-delete (corbeille) des conversations de test fournies. Ne touche jamais
    une vraie conversation : double filtre heuristique côté service."""
    agent_ids = (json_body(request)).get("agent_ids") or []
    if not isinstance(agent_ids, list):
        return jsonify({"error": "agent_ids doit être une liste"}), 400
    return jsonify(purge.purge_agents(agent_ids))


@sessions_bp.post("/api/conversations/<agent_id>/archive")
def api_conversation_archive(agent_id: str):
    """Archive (rangement réversible) une conversation quelconque, y compris une vraie
    conversation user finie. Refuse un agent inconnu.

    N'écrit QUE dans le registre des archivés : rien n'est déplacé sur disque (le
    déplacement a rendu un manager vivant injoignable le 2026-07-28, cf. purge.archive_agents),
    et un agent encore vivant reste visible malgré le drapeau (cf. sessions/visibility.py)."""
    return jsonify(purge.archive_agents([agent_id]))


@sessions_bp.post("/api/conversations/auto-purge-tests")
def api_conversations_auto_purge_tests():
    """Purge automatique des conversations de test non-running (remplace le bouton
    manuel). Appelée par le front au chargement de la page conversations."""
    return jsonify(purge.auto_purge_test_agents())


@sessions_bp.get("/api/conversations/stale-need-input")
def api_conversations_stale_need_input():
    """Conversations bloquées en 'need input' avec un process MORT (orphelines).
    Le frontend peut proposer de les archiver en masse."""
    return jsonify({"candidates": purge.stale_need_input_candidates()})


@sessions_bp.post("/api/conversations/auto-archive-stale")
def api_conversations_auto_archive_stale():
    """Archive automatiquement les conversations 'need input' orphelines (process mort)
    de plus de 12h. Appelée par le front au chargement de /conversations. Réversible."""
    return jsonify(purge.auto_archive_stale_need_input())


@sessions_bp.post("/api/conversations/archive")
def api_conversations_archive():
    """Archive (soft-delete réversible) une ou plusieurs conversations.

    Body: {"keys": ["agent/<id>", ...]} (id bruts acceptés aussi).
    Réponse: {"archived": [agent_id...], "skipped": [{"agent_id", "reason"}...]} (id bruts).
    Fonctionne pour TOUTES les natures, notamment "user". Réversible via
    POST /api/sessions/<key>/restore."""
    keys = (json_body(request)).get("keys") or []
    if not isinstance(keys, list):
        return jsonify({"error": "keys doit être une liste"}), 400
    return jsonify(purge.archive_agents(keys))


@sessions_bp.post("/api/conversations/<agent_id>/relaunch")
def api_conversation_relaunch(agent_id: str):
    text = ((json_body(request)).get("text") or "").strip()
    prompt = text or recovery.DEFAULT_RELAUNCH_PROMPT
    new_id = recovery.relaunch(agent_id, prompt)
    if new_id is None:
        return jsonify({"error": "agent inconnu"}), 404
    return jsonify({"ok": True, "agent_id": new_id, "key": f"agent/{new_id}"})


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


@sessions_bp.get("/api/sessions/<path:key>/turns/<int:n>/context")
def api_session_turn_context(key: str, n: int):
    """Diagnostic du contexte injecté au modèle pour le tour `n` d'une session.

    Restauration de la 1re implémentation (perdue dans un stash auto-integrate).
    `?json=1` → payload brut (dict) ; sinon → page HTML riche (delta/cached/tokens).
    """
    from ..services.sessions.context_diag import build_turn_context_diag
    from ..services.sessions.context_diag_render import render_context_diag_html
    from ..services.sessions.formatter import pretty_json

    ref, err = _resolve_or_404(key)
    if err is not None:
        return err
    diag = build_turn_context_diag(str(ref.path), n)
    if diag is None:
        return jsonify({"error": f"aucun diagnostic pour le tour {n}"}), 404
    if request.args.get("json"):
        resp = make_response(pretty_json(diag))
        resp.headers["Content-Type"] = "application/json"
        return resp
    resp = make_response(render_context_diag_html(diag))
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


@sessions_bp.post("/api/sessions/purge-test")
def api_sessions_purge_test():
    dry = bool((json_body(request)).get("dry"))
    return jsonify(purge.purge_test_sessions(dry=dry))


@sessions_bp.post("/api/sessions/<path:key>/restore")
def api_session_restore(key: str):
    ok = purge.restore(key)
    return jsonify({"ok": ok, "key": key})


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


def _status_with_liveness(agent) -> dict:
    """Statut de session SERVI au front, enrichi de la VIVACITÉ dérivée de preuves.

    `state` ne dit que « la session est close » : le panneau de détail affichait donc
    « terminé » pour un agent mort sans avoir rien livré, pendant que la sidebar le disait
    « mort ? » et la liste de tickets « planté ». On sert ici la MÊME vivacité que
    `/api/agents/tree` et la liste de tickets (`liveness.classify_agent`) pour que le front
    n'ait AUCUNE règle à redériver. `interrupted` (bouton « décider de son sort ») est
    exactement « mort sans clôture prouvée », donc lu sur cette vivacité."""
    if agent is None:
        return {"state": "cli"}
    status = store.agent_status(agent)
    live = liveness.classify_agent(agent, status.get("state", ""))
    return {**status, "liveness": live, "interrupted": live == "crashed"}


_LAUNCHING_PREFIX = "launching/"


def _launching_blocks(ticket_id: str):
    """Réponse `/blocks` d'une conversation ENCORE EN PROVISIONNEMENT (clé `launching/<id>`).

    Il n'y a rien à streamer — aucun agent, aucune session — mais il y a quelque chose à DIRE :
    quelle étape tourne (`git worktree add`, `uv sync`, spawn) et depuis quand. Sans cette
    branche la route rendait 404 sur toute la durée du provisionnement, et c'est très exactement
    ce trou que le front comblait par une phrase figée."""
    status = launch_phase.status_for(ticket_id)
    if status is None:
        # Plus aucun lancement pour ce ticket : l'agent vient de naître (le front bascule alors
        # l'onglet sur `agent/<id>`, cf. remapLaunchingTabs) ou le lancement a échoué.
        return jsonify({"error": f"aucun lancement en cours: {ticket_id}"}), 404
    return jsonify({"total": 0, "blocks": [], "status": status, "meta": {}})


@sessions_bp.get("/api/sessions/<path:key>/blocks")
def api_session_blocks(key: str):
    if key.startswith(_LAUNCHING_PREFIX):
        return _launching_blocks(key[len(_LAUNCHING_PREFIX):])
    ref, error = _resolve_or_404(key)
    if error:
        return error
    after = max(0, request.args.get("after", 0, type=int))
    plain = bool(request.args.get("plain"))
    data = store.load_session_json(ref.path)
    status = _status_with_liveness(ref.agent)
    if data is None:
        return jsonify({"total": 0, "blocks": [], "status": status,
                        "meta": {}, "note": "session pas encore écrite ou illisible"})
    messages = data.get("messages") or []
    if plain:
        blocks = [_plain_block(i, messages[i]) for i in range(after, len(messages))]
    else:
        # Numérotation GLOBALE des tours (assistant = 1 tour, 1-based) calculée
        # depuis le début pour survivre au polling incrémental (after>0). Le bouton
        # « ? » de chaque bulle assistant utilise ce turn_index pour ouvrir
        # /api/sessions/<key>/turns/<n>/view (contexte injecté du tour).
        turn_by_index: dict[int, int] = {}
        turn_counter = 0
        for j in range(len(messages)):
            if messages[j].get("role") == "assistant":
                turn_counter += 1
                turn_by_index[j] = turn_counter
        blocks = [
            {
                "idx": i,
                "html": message_view.render_message(
                    messages[i],
                    context_url=(
                        f"/api/sessions/{key}/turns/{turn_by_index[i]}/context"
                        if i in turn_by_index
                        else None
                    ),
                ),
            }
            for i in range(after, len(messages))
        ]
        # T4 — marqueurs inline « N agent(s) lancé(s) ». Uniquement au chargement complet
        # (after==0) pour ne pas casser la numérotation du polling incrémental : ces blocs
        # synthétiques n'entrent PAS dans `total` (= nombre de vrais messages). Correct après
        # reload ET sur sessions historiques (backfill : croise runs[].started_at du ticket).
        if after == 0 and ref.agent is not None:
            blocks = _interleave_subagent_events(blocks, messages, ref.agent)
    return jsonify({
        "total": len(messages),
        "blocks": blocks,
        "status": status,
        "meta": store.session_meta_full(data),
    })


def _interleave_subagent_events(blocks: list, messages: list, agent) -> list:
    """Intercale les blocs subagent_event du ticket de `agent` à leur position chronologique.
    Ancrage sans timestamp par message : le kème groupe de lancement suit la kème livraison
    (message tool FinalAnswer « Session closing »). Fallback : fin du fil."""
    events = subagent_events.build_events(agent)
    if not events:
        return blocks
    # Indices des livraisons du codeur, dans l'ordre du fil.
    deliveries = [
        i for i, m in enumerate(messages)
        if m.get("role") == "tool"
        and message_view._final_answer_kind(str(m.get("name", "")), message_view._content_text(m)) == "final_answer"
    ]
    # Grouper les events par vague de lancement : un launch ouvre une vague, ses done suivent.
    waves: list[list[dict]] = []
    for ev in events:
        if ev["subtype"] == "launch":
            waves.append([ev])
        elif waves:
            waves[-1].append(ev)
        else:
            waves.append([ev])
    # anchor_idx[k] = index du message après lequel insérer la kème vague.
    result: list = []
    # Map: après quel idx de message insérer quelles vagues.
    inserts: dict[int, list[dict]] = {}
    for k, wave in enumerate(waves):
        anchor = deliveries[k] if k < len(deliveries) else (len(messages) - 1)
        inserts.setdefault(anchor, []).extend(wave)
    for block in blocks:
        result.append(block)
        for ev in inserts.get(block["idx"], []):
            result.append({"idx": block["idx"], "html": message_view.render_message(ev)})
    # Vagues sans ancrage valide (anchor hors des blocs rendus) → append en fin.
    rendered_anchors = {b["idx"] for b in blocks}
    for anchor, evs in inserts.items():
        if anchor not in rendered_anchors:
            for ev in evs:
                result.append({"idx": anchor, "html": message_view.render_message(ev)})
    return result


@sessions_bp.get("/api/sessions/<path:key>/partial")
def api_session_partial(key: str):
    """Live partial assistant text of the running turn (token streaming).

    Reads ``<session>.partial.json`` written by the runner
    (``backend.agent.partial_stream.write_partial``) on every ``TextChunk``.
    Returns ``{"turn","seq","text"}`` while a message is being produced, or
    ``{"text": None}`` when no partial exists (idle / message just persisted)."""
    ref, error = _resolve_or_404(key)
    if error:
        return error
    partial_path = ref.path.with_suffix(".partial.json")
    import json as _json
    for attempt in range(2):
        try:
            data = _json.loads(partial_path.read_text(encoding="utf-8"))
            return jsonify({
                "turn": data.get("turn"),
                "seq": data.get("seq"),
                "phase": data.get("phase", "text"),
                "text": data.get("text"),
                "thinking": data.get("thinking", ""),
            })
        except FileNotFoundError:
            return jsonify({"text": None})
        except (OSError, _json.JSONDecodeError):
            if attempt == 0:
                import time as _time
                _time.sleep(0.03)
    return jsonify({"text": None})


@sessions_bp.get("/api/sessions/<path:key>/overview")
def api_session_overview(key: str):
    ref, error = _resolve_or_404(key)
    if error:
        return error
    data = store.load_session_json(ref.path)
    if data is None:
        return jsonify({"error": "session pas encore écrite ou illisible"}), 404

    after = request.args.get("after", 0, type=int)
    limit = request.args.get("limit", 30, type=int)

    result = overview.build_overview(data, key, after=after, limit=limit)

    if request.args.get("json"):
        from ..services.sessions.formatter import pretty_json
        resp = make_response(pretty_json(result))
        resp.content_type = "application/json"
        return resp
    else:
        plain_text = overview.format_plain(result, key)
        resp = make_response(plain_text)
        resp.content_type = "text/plain; charset=utf-8"
        return resp


@sessions_bp.get("/api/sessions/<path:key>/recap")
def api_session_recap(key: str):
    """Structured recap of a session (symptoms/explanation/tests/changes). Persisted
    by the FinalAnswer close gate. A dead/crashed session with no recap returns a
    graceful placeholder rather than a 404, so the UI/PR message always has text."""
    ref, error = _resolve_or_404(key)
    if error:
        return error
    data = store.load_session_json(ref.path)
    if data is None:
        return jsonify({"error": "session pas encore écrite ou illisible"}), 404
    recap = data.get("recap")
    snapshots = data.get("file_snapshots") or {}
    if isinstance(recap, dict) and recap:
        return jsonify({"recap": recap,
                        "recap_missing": bool(data.get("recap_missing")),
                        "diffs": recap_service.session_recap_diffs(recap, data)})
    # Pas de récap propre : si c'est un MANAGER, concaténer les récaps des sous-agents
    # (parent==agent_id) → vue consolidée du lot, sans LLM.
    if ref.kind == "agent" and ref.agent is not None:
        children = recap_service.aggregate_children_recaps(
            ref.agent.agent_id, runner.list_agents(),
            lambda p: store.load_session_json(Path(p)),
            find_verdict=_find_verdict)
        if children:
            return jsonify({"recap": None, "recap_missing": False,
                            "is_aggregate": True, "children": children, "diffs": []})
    return jsonify({
        "recap": None,
        "recap_missing": True,
        "note": "session interrompue, récap indisponible",
        "diffs": recap_service.session_recap_diffs(None, data),
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


@sessions_bp.get("/api/sessions/<path:key>/turns/<int:n>/view")
def api_session_turn_view(key: str, n: int):
    ref, error = _resolve_or_404(key)
    if error:
        return error
    data = store.load_session_json(ref.path)
    if data is None:
        return jsonify({"error": "session pas encore écrite ou illisible"}), 404

    from ..services.sessions.turn_view import format_turn_view, format_turn_plain

    thinking = request.args.get("thinking", "0") == "1"
    result = format_turn_view(data.get("messages") or [], key, n, thinking=thinking)
    if result is None:
        return jsonify({"error": f"tour {n} introuvable"}), 404

    if request.args.get("json"):
        from ..services.sessions.formatter import pretty_json
        resp = make_response(pretty_json(result))
        resp.content_type = "application/json"
    else:
        resp = make_response(format_turn_plain(result))
        resp.content_type = "text/plain; charset=utf-8"
    return resp


@sessions_bp.get("/api/sessions/<path:key>/calls/<call_id>")
def api_session_call_zoom(key: str, call_id: str):
    ref, error = _resolve_or_404(key)
    if error:
        return error
    data = store.load_session_json(ref.path)
    if data is None:
        return jsonify({"error": "session pas encore écrite ou illisible"}), 404

    from ..services.sessions.call_zoom import get_call_detail, format_call_plain

    result = get_call_detail(data.get("messages") or [], call_id)
    if result is None:
        return jsonify({"error": f"call_id '{call_id}' introuvable"}), 404

    if request.args.get("json"):
        from ..services.sessions.formatter import pretty_json
        resp = make_response(pretty_json(result))
        resp.content_type = "application/json"
    else:
        resp = make_response(format_call_plain(result))
        resp.content_type = "text/plain; charset=utf-8"
    return resp


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
    from .. import api_sanity
    guard = api_sanity.require_api_sanity()
    if guard is not None:
        return guard
    payload = json_body(request)
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt requis"}), 400
    cwd = payload.get("cwd") or str(file_service.ROOT)
    # Resolve typology → profile
    from ..services.typologies import get_typology
    typology_name = payload.get("typology") or ""
    typo = get_typology(typology_name, cwd) if typology_name else None
    profile = typo["profile"] if typo else ""
    try:
        agent = runner.create_agent(
            prompt, payload.get("model") or "", cwd,
            profile=profile,
            parent=payload.get("parent") or "",
        )
    except runner.MissingProviderEnvError as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"key": f"agent/{agent.agent_id}", "agent_id": agent.agent_id})


@sessions_bp.post("/api/agents/<agent_id>/continue")
def api_agent_continue(agent_id: str):
    agent = runner.load_agent(agent_id)
    if agent is None:
        # NOMMER l'échec : l'enregistrement de l'agent est introuvable, donc le message
        # n'est PAS parti et ne partira jamais tant que la fiche n'est pas restaurée.
        # `reason` permet au front de ne pas confondre ce cas définitif avec un agent
        # occupé (qu'on interrompt puis relance) — cf. `sendMsg` dans conversations.js.
        return jsonify({
            "error": f"agent {agent_id} introuvable : son enregistrement a disparu du parc "
                     f"d'agents. RIEN n'a été envoyé — restaure sa fiche (elle peut être "
                     f"dans web_agents/_trash/) avant de réessayer.",
            "reason": "agent_missing",
        }), 404
    # Le bouton "Reprendre" (agents interrompus) POST body {text:""} : relancer le
    # tour d'un agent crashé/interrompu SANS nouveau message est un cas LÉGITIME.
    # continue_agent gère déjà text vide (session vide → rejoue le prompt d'origine ;
    # session avec tours → poursuit). Ne PAS rejeter en 400 : ça cassait "Reprendre".
    text = ((json_body(request)).get("text") or "").strip()
    status = store.agent_status(agent)
    # La garde n'existe que pour EMPÊCHER DEUX TOURS CONCURRENTS sur la même session. Elle
    # ne vaut donc QUE contre un agent réellement en plein tour (`running`). Un agent chaud
    # mais OISIF (`idle` : process résident du warm pool, aucun tour en cours) se faisait
    # refuser par cette même garde et devenait INJOIGNABLE — 20 min de 409 sur le manager
    # 0123456789ab, débloqué seulement en tuant son process. `agent_status` distingue
    # désormais les deux ; ici on ne fait que cesser de les confondre. Ne PAS élargir ce
    # refus : c'est lui qui protège la session du double tour.
    if status["state"] == "running":
        return jsonify({"error": "l'agent tourne encore — attends la fin du tour",
                        "reason": "running"}), 409
    # A merged ticket's worktree is cleaned away; without a valid cwd the respawn below crashes
    # (NotADirectoryError → 500). Re-home to a fresh worktree (or repo_root) first.
    #
    # RIEN à re-homer pour un agent chaud : aucun respawn n'aura lieu (voir plus bas), et le
    # cwd d'un process DÉJÀ lancé ne se change pas. `rehome_agent_cwd` serait au mieux un
    # no-op (son worktree est vivant, puisqu'un process y tourne), au pire une réisolation
    # sous les pieds d'un agent en vie. On s'abstient.
    if status["state"] != "idle":
        dispatch.rehome_agent_cwd(agent)
    # Même raison que messaging.send_to_ticket_agent : l'agent repart, donc la récolte de
    # sa livraison précédente ne couvre plus le travail qu'il va produire (cf. delivery.py).
    delivery.reopen_for_new_work(getattr(agent, "ticket_slug", "") or "",
                                 getattr(agent, "ticket_id", "") or "")
    # CHEMIN D'ÉCRITURE : `continue_agent` choisit déjà seul entre reprise CHAUDE et
    # respawn (`_is_warm` → `_push_followup`). Pour un agent oisif il pousse le texte dans
    # followup.txt, que l'idle-loop du process pop et joue IN-PROCESS : contexte conservé en
    # RAM, zéro cold-start. Le respawn serait ici le mauvais chemin — il faudrait d'abord
    # tuer un process parfaitement sain, et la garde anti-double-spawn de `_respawn` le
    # refuserait de toute façon. Rien à ajouter donc : il suffisait que l'appel ait lieu.
    # UNE QUESTION EST UNE QUESTION, quel que soit son type. `awaiting_plan_validation` (plan
    # à valider) et `awaiting_input` (AskUserQuestion) mettent le MÊME tour en pause et
    # persistent le MÊME `<session>.pending.json` — c'est ce que dit déjà
    # `awaiting.AWAITING_STATES`. En n'acceptant ici que `awaiting_input`, la réponse à une
    # validation de plan partait en `continue_agent` : un tour NEUF au lieu de la reprise du
    # tour en pause, et le pending n'était JAMAIS consommé — la conversation restait
    # « à répondre » pour toujours, même après que l'utilisateur eut validé.
    if status["state"] in awaiting.AWAITING_STATES and pending.exists(agent.session_path):
        delivered = runner.resume_pending_agent(agent, text)
    else:
        delivered = runner.continue_agent(agent, text)
    # RIEN N'A ÉTÉ REMIS À L'AGENT. `_respawn` refuse de lancer un jumeau tant qu'un process
    # tourne pour cette session et rend `None` ; ce None n'était pas lu et la route répondait
    # quand même `{"ok": true}` — le message de l'utilisateur disparaissait sans une trace, ni
    # côté serveur ni côté écran. Aucune erreur ne doit être avalée : on la NOMME, et le front
    # sait déjà quoi faire d'un 409 (interrompre puis réessayer).
    if delivered is None:
        return jsonify({
            "error": "un process tourne déjà pour cette session : le message n'a PAS été "
                     "transmis. Interromps l'agent (Ctrl+C) puis réessaie.",
            "reason": "not_delivered",
        }), 409
    # Le respawn (continue_agent/resume_pending_agent) relance le process, mais le statut
    # "finished" a été mémorisé SANS TTL dans store._status_cache → agent_status() le renvoie
    # à vie et court-circuite is_running(). Résultat : l'agent re-tourne réellement mais la
    # sidebar le laisse en « Terminés ». On purge l'entrée ici pour que le prochain
    # agent_status() recalcule (is_running=True → "running" → section « En cours »).
    store.invalidate_status(agent_id)
    return jsonify({"ok": True})


@sessions_bp.post("/api/agents/<agent_id>/kill")
def api_agent_kill(agent_id: str):
    agent = runner.load_agent(agent_id)
    if agent is None:
        return jsonify({"error": "agent inconnu"}), 404
    runner.kill_agent(agent)
    return jsonify({"ok": True})


@sessions_bp.post("/api/agents/<agent_id>/interrupt")
def api_agent_interrupt(agent_id: str):
    """Interruption d'abord DOUCE (cancel.flag), puis ESCALADE si l'agent ne cède pas.

    Le tour en cours s'arrête proprement au prochain point d'interruption (comme Ctrl+C
    dans le TUI), l'agent repasse en idle — process CONSERVÉ, donc le /continue suivant le
    réveille à chaud (zéro cold-start) au lieu de le respawner. Un agent coincé HORS point
    d'interruption ne verrait jamais le flag : s'il tient toujours son tour après ~1,5 s de
    grâce, son process est TUÉ (`escalated: true` dans la réponse). Ce n'est donc pas une
    interruption purement douce — la description de l'API le dit désormais aussi.

    Un refus de l'OS (`AccessDenied` : process en train de mourir, pid recyclé, ACL) est un
    RÉSULTAT, pas une panne : il est rendu tel quel (`ok: false` + `error`) et inscrit sur
    l'agent, au lieu de faire 500 la route — et, par `list_agents`, tout le serveur."""
    agent = runner.load_agent(agent_id)
    if agent is None:
        return jsonify({"error": "agent inconnu"}), 404
    # 1) Interruption douce : cancel.flag laisse le tour en cours s'arrêter proprement
    #    (sauvegarde du partial) au prochain point d'interruption.
    runner.graceful_cancel_agent(agent)
    # 2) Escalade bornée : si l'agent est COINCÉ hors point d'interruption (appel LLM/réseau
    #    long, boucle qui ne consomme pas le flag), il ne s'arrête jamais → le front reboucle
    #    /continue en 409 pendant 120s → toast "n'a pas pu être interrompu". Après une courte
    #    grâce, s'il TIENT ENCORE SON TOUR on le tue (terminate + reap du twin).
    #
    #    `is_mid_turn` et non `is_running` : un agent chaud garde son process APRÈS avoir cédé
    #    (warm pool), donc « pid vivant » condamnait au kill même les annulations réussies —
    #    et transformait le message suivant en cold-respawn. On sonde AVANT de dormir : un
    #    agent déjà oisif n'a aucune raison de faire attendre l'appelant 1,5 s.
    for _ in range(3):
        if not runner.is_mid_turn(agent):
            break
        time.sleep(0.5)
    if not runner.is_mid_turn(agent):
        return jsonify({"ok": True, "escalated": False})
    outcome = runner.kill_agent(agent)
    if outcome.get("error"):
        _report_interrupt_failure(agent, outcome["error"])
        return jsonify({"ok": False, "escalated": True, "error": outcome["error"]})
    return jsonify({"ok": True, "escalated": True})


def _report_interrupt_failure(agent, error: str) -> None:
    """Rend l'échec VISIBLE là où l'utilisateur regarde : sur le ticket de l'agent (il est
    déjà inscrit sur l'agent par `runner.signal_termination`). Sans ticket rattaché, le
    champ de l'agent reste le seul témoin — c'est le cas des conversations hors ticket."""
    slug = getattr(agent, "ticket_slug", "") or ""
    ticket_id = getattr(agent, "ticket_id", "") or ""
    if not (slug and ticket_id):
        return
    ticket = tickets.get_ticket(slug, ticket_id)
    if ticket is None:
        return
    tickets.add_comment(slug, ticket, _INTERRUPT_REFUSED.format(
        agent_id=agent.agent_id, error=error), True)
