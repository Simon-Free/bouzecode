# [desc] API manager : dispatch zéro-champ d'un prompt + arbre des agents tous projets. [/desc]
from __future__ import annotations

import threading

from flask import Blueprint, jsonify, request

from .._body import json_body

from ...runtime import runner
from ...services import scope_guard
from ...services.work import dispatch as dispatch_service
from ...services.work import activity, fleet, messaging

fleet_bp = Blueprint("fleet_api", __name__)


@fleet_bp.post("/api/dispatch")
def api_dispatch():
    """Un prompt → projet/typologie/modèle déduits puis ticket + agent lancés.
    Overrides optionnels: project_slug, typology, model. parent défaut = manuel."""
    from ... import api_sanity
    guard = api_sanity.require_api_sanity()
    if guard is not None:
        return guard
    payload = json_body(request)
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt requis"}), 400
    try:
        result = dispatch_service.dispatch(
            prompt,
            project_slug=payload.get("project_slug") or "",
            typology=payload.get("typology") or "",
            model=payload.get("model") or "",
            parent=payload.get("parent") or dispatch_service._MANUAL_PARENT,
            # Choix d'isolation du manager (ou de l'humain) : shared | worktree | worktree+venv.
            # Défaut shared ; le serveur ne rattrape QUE la collision de deux shared (garde-fou).
            isolation=payload.get("isolation") or dispatch_service.SHARED,
            use_readme=bool(payload.get("use_readme")),  # case UI : autorise usage/modif des README.md à l'exploration
            defer=bool(payload.get("defer")),  # True = renvoie ticket_id vite, launch en fond
            ephemeral=bool(payload.get("ephemeral")),  # True = test jetable, jamais mergé sur la base
            resume_branch=payload.get("resume_branch") or "",  # worktree DEPUIS cette branche (point de départ)
            # branche EXISTANTE sur laquelle l'agent travaille (ses commits y vont directement).
            # Refus 200 {routed:false, error} si elle est inconnue ou déjà sortie ailleurs.
            work_branch=payload.get("work_branch") or "",
        )
    except runner.MissingProviderEnvError as exc:
        return jsonify({"error": str(exc)}), 500
    # Garde-fou de PÉRIMÈTRE (cf. services/scope_guard) : un manager qui dispatche deux
    # tickets au périmètre manifestement identique, ou qui brieffe « READ-ONLY » un ticket
    # dont la typologie accorde Write/Edit/Bash, doit être SIGNALÉ. Il signale sans refuser
    # (jugement heuristique) : drapeau + commentaire sur le ticket, avertissement rendu ici
    # au manager — le seul acteur capable de corriger son découpage.
    if result.get("routed") and result.get("ticket_id"):
        warnings = scope_guard.review_dispatch(
            result["project_slug"], result["ticket_id"], prompt,
            result.get("typology") or "", payload.get("parent") or "",
        )
        # ÉTENDRE, jamais écraser : `dispatch` peut déjà y avoir posé ses propres
        # avertissements (correction d'isolation décidée par le serveur). Une affectation
        # les effaçait — et un avertissement effacé est pire qu'absent, la chaîne tourne
        # en donnant l'illusion d'avoir prévenu.
        if warnings:
            result.setdefault("scope_warnings", []).extend(warnings)
    # Un dispatch AJOUTE un process au parc : c'est le moment causal de reborner le
    # warm-pool. Ce ménage était auparavant déclenché par GET /api/agents/tree — une
    # lecture qui tuait des process. Le tick du watchdog reste à brancher pour couvrir
    # le cas « aucun dispatch pendant des heures » (cf. fleet.sweep_warm_pool).
    #
    # EN FOND, jamais dans la réponse : le ménage n'apporte rien au lancement demandé, mais
    # il RELIT tout le parc pour décider qui évincer. Mesuré le 2026-08-03 sur le parc réel
    # (324 agents, 264 sessions), ses deux briques coûtent 13,6 s (`runner.list_agents`) et
    # 14,6 s (`store.list_agent_sessions`) quand le cache disque est froid — 7,3 s observées
    # au navigateur sur un POST /api/dispatch réel. L'utilisateur attendait donc l'entretien
    # du parc avant de voir que sa demande était partie. Le thread garde le moment causal
    # sans le facturer à la réponse.
    threading.Thread(target=fleet.sweep_warm_pool, daemon=True,
                     name="sweep-warm-pool").start()
    return jsonify(result)


@fleet_bp.post("/api/agent/message")
def api_agent_message():
    """Le manager ré-instruit un enfant DÉJÀ lancé (même agent, contexte gardé),
    identifié par son ticket_id. 404 si ticket introuvable, 400 si texte vide,
    409 si l'agent tourne encore ; sinon 200."""
    payload = json_body(request)
    ticket_id = (payload.get("ticket_id") or "").strip()
    text = (payload.get("text") or "").strip()
    resolved = messaging.resolve_ticket(ticket_id)
    if resolved is None:
        return jsonify({"error": f"ticket inconnu: {ticket_id}"}), 404
    if not text:
        return jsonify({"error": "text requis"}), 400
    slug, ticket = resolved
    result = messaging.send_to_ticket_agent(slug, ticket, text)
    if not result["ok"]:
        return jsonify({"error": result["error"]}), result.get("code", 409)
    return jsonify(result)


@fleet_bp.get("/api/agents/tree")
def api_agent_tree():
    """Arbre des agents. `?offset=&limit=` sert `limit` RACINES à partir d'`offset`,
    chacune avec ses sous-agents, + `total_roots`. Sans `limit`, l'arbre complet."""
    offset = max(_int_arg("offset", 0), 0)
    limit = _int_arg("limit", 0)
    return jsonify(fleet.agent_tree(offset=offset, limit=limit if limit > 0 else None))


@fleet_bp.get("/api/agents/activity")
def api_agents_activity():
    """Ce que fait CHAQUE agent vivant : outil en cours, tour, âge du dernier battement,
    silence anormal — plus les tickets en cours de lancement avec leur phase.

    Vue de SURVEILLANCE, taillée pour être appelée souvent : aucun subprocess git, aucun
    prompt, aucun agent terminé. À préférer à /api/agents/tree pour du monitoring — l'arbre
    complet coûte ~9,5 s et 929 Ko parce qu'il sert le parc entier avec ses infos git."""
    return jsonify(activity.report())


def _int_arg(name: str, default: int) -> int:
    """Paramètre de requête entier ; une valeur absente ou non numérique vaut `default`."""
    raw = (request.args.get(name) or "").strip()
    return int(raw) if raw.lstrip("-").isdigit() else default
