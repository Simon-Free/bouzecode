# [desc] API tickets: créer & lancer, follow-up commentaires vers l'agent, validations CI, terminer. [/desc]
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ....web import pending, runner
from ...services.sessions import store
from ...services.work import projects, results, tickets

tickets_bp = Blueprint("tickets_api", __name__)


def _project_or_404(slug: str):
    project = projects.find(slug)
    if project is None:
        return None, (jsonify({"error": f"projet inconnu: {slug}"}), 404)
    return project, None


def _ticket_or_404(slug: str, ticket_id: str):
    ticket = tickets.get_ticket(slug, ticket_id)
    if ticket is None:
        return None, (jsonify({"error": f"ticket inconnu: {ticket_id}"}), 404)
    return ticket, None


@tickets_bp.get("/api/projects/<slug>/tickets")
def api_tickets_list(slug: str):
    project, error = _project_or_404(slug)
    if error:
        return error
    rows = tickets.list_tickets(slug, refresh=True)
    return jsonify({"tickets": [
        {**ticket, "status": tickets.derive_status(ticket)} for ticket in rows
    ]})


@tickets_bp.post("/api/projects/<slug>/tickets")
def api_tickets_create(slug: str):
    project, error = _project_or_404(slug)
    if error:
        return error
    payload = request.get_json(force=True) or {}
    title = (payload.get("title") or "").strip()
    prompt = (payload.get("prompt") or "").strip()
    if not title or not prompt:
        return jsonify({"error": "title et prompt requis"}), 400
    ticket = tickets.create_ticket(slug, title, prompt)
    if payload.get("launch", True):
        # Resolve typology → profile
        from ...services.typologies import get_typology
        typology_name = payload.get("typology") or ""
        typo = get_typology(typology_name, project["path"]) if typology_name else None
        profile = typo["profile"] if typo else ""
        paralysis = payload.get("paralysis_abort_after")
        try:
            agent = runner.create_agent(
                prompt, payload.get("model") or "", project["path"],
                profile=profile, paralysis_abort_after=paralysis,
            )
        except runner.MissingProviderEnvError as exc:
            return jsonify({"error": str(exc)}), 500
        tickets.add_run(slug, ticket, agent.agent_id, "work", payload.get("model") or "")
    return jsonify(ticket)


@tickets_bp.post("/api/tickets/<slug>/<ticket_id>/launch")
def api_ticket_launch(slug: str, ticket_id: str):
    project, error = _project_or_404(slug)
    if error:
        return error
    ticket, error = _ticket_or_404(slug, ticket_id)
    if error:
        return error
    payload = request.get_json(force=True) or {}
    model = payload.get("model") or ""
    # Resolve typology → profile
    from ...services.typologies import get_typology
    typology_name = payload.get("typology") or ""
    typo = get_typology(typology_name, project["path"]) if typology_name else None
    profile = typo["profile"] if typo else ""
    paralysis = payload.get("paralysis_abort_after")
    try:
        agent = runner.create_agent(
            ticket["prompt"], model, project["path"],
            profile=profile, paralysis_abort_after=paralysis,
        )
    except runner.MissingProviderEnvError as exc:
        return jsonify({"error": str(exc)}), 500
    tickets.add_run(slug, ticket, agent.agent_id, "work", model)
    return jsonify({"key": f"agent/{agent.agent_id}"})


@tickets_bp.post("/api/tickets/<slug>/<ticket_id>/validate")
def api_ticket_validate(slug: str, ticket_id: str):
    project, error = _project_or_404(slug)
    if error:
        return error
    ticket, error = _ticket_or_404(slug, ticket_id)
    if error:
        return error
    payload = request.get_json(force=True) or {}
    kind = payload.get("kind") or ""
    if kind not in tickets.VALIDATORS:
        return jsonify({"error": f"kind invalide: {kind} (tests|refacto)"}), 400
    prompt = tickets.VALIDATORS[kind].format(title=ticket["title"], prompt=ticket["prompt"])
    model = payload.get("model") or ""
    agent = runner.create_agent(prompt, model, project["path"])
    tickets.add_run(slug, ticket, agent.agent_id, f"validate_{kind}", model)
    return jsonify({"key": f"agent/{agent.agent_id}"})


@tickets_bp.post("/api/tickets/<slug>/<ticket_id>/comments")
def api_ticket_comment(slug: str, ticket_id: str):
    ticket, error = _ticket_or_404(slug, ticket_id)
    if error:
        return error
    payload = request.get_json(force=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text requis"}), 400
    sent = False
    if payload.get("send"):
        work_run = next((r for r in ticket["runs"] if r["kind"] == "work"), None)
        agent = runner.load_agent(work_run["agent_id"]) if work_run else None
        if agent is None:
            return jsonify({"error": "aucun run de travail à relancer"}), 409
        if store.agent_status(agent)["state"] == "running":
            return jsonify({"error": "l'agent tourne encore — attends la fin du tour"}), 409
        if pending.exists(agent.session_path):
            runner.resume_pending_agent(agent, text)
        else:
            runner.continue_agent(agent, text)
        sent = True
    tickets.add_comment(slug, ticket, text, sent)
    return jsonify({"ok": True, "sent": sent})


@tickets_bp.get("/api/tickets/<slug>/<ticket_id>/results")
def api_ticket_results(slug: str, ticket_id: str):
    project, error = _project_or_404(slug)
    if error:
        return error
    ticket, error = _ticket_or_404(slug, ticket_id)
    if error:
        return error
    return jsonify(results.ticket_results(project, ticket))


@tickets_bp.post("/api/tickets/<slug>/<ticket_id>/done")
def api_ticket_done(slug: str, ticket_id: str):
    ticket, error = _ticket_or_404(slug, ticket_id)
    if error:
        return error
    ticket["done"] = not ticket.get("done", False)
    tickets.update_ticket(slug, ticket)
    return jsonify({"done": ticket["done"]})
