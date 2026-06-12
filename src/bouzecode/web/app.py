# [desc] BouzéqUI Flask web application providing UI routes for managing agents, skills, and tools. [/desc]
"""BouzéqUI Flask app — main web interface for bouzecode."""
from __future__ import annotations

import argparse
import atexit
import signal
import time
from datetime import datetime
from pathlib import Path

import markdown as md
from flask import Flask, Response, jsonify, redirect, render_template, request, url_for

from . import context_viewer, dashboard_service, kanban, pending as web_pending, projects, runner, session_service, skills_service, state_streams, todo, tools_service

from .stdout_filter import clean_stdout as _clean_stdout


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )

    # Respawn agents that were killed when the server last stopped
    resumed = runner.resume_interrupted_agents()
    if resumed:
        print(f"[bouzequi] Resumed {len(resumed)} interrupted agent(s): "
              + ", ".join(a.agent_id for a in resumed))

    _MONTHS_FR = ["jan", "fev", "mar", "avr", "mai", "jun",
                  "jul", "aou", "sep", "oct", "nov", "dec"]

    @app.template_filter("fmt_date")
    def _fmt_date(iso_str: str) -> str:
        if not iso_str:
            return ""
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            month = _MONTHS_FR[dt.month - 1]
            return f"{dt.day} {month}. {dt.year} {dt.hour:02d}:{dt.minute:02d}"
        except (ValueError, IndexError):
            return iso_str

    @app.route("/")
    def home():
        return redirect(url_for("agents_page"))

    # --- Dashboard --------------------------------------------------------

    @app.route("/dashboard")
    def dashboard_page():
        data = dashboard_service.get_dashboard_data()
        return render_template("dashboard/overview.html", data=data)

    # --- Agents -----------------------------------------------------------

    @app.route("/agents")
    def agents_page():
        agents = runner.list_agents()
        running, awaiting, finished = [], [], []
        for agent in agents:
            ipc_state = runner.get_ipc_state(agent)
            ipc_status = ipc_state.get("status")
            alive = runner.is_running(agent)
            if ipc_status in ("awaiting_input", "awaiting_plan_validation"):
                has_pending = agent.session_path and web_pending.exists(agent.session_path)
                if not alive and not has_pending:
                    finished.append(agent)
                else:
                    awaiting.append(agent)
            elif not alive or ipc_status == "finished":
                finished.append(agent)
            else:
                running.append(agent)
        finished.sort(key=lambda a: a.finished_at or "", reverse=True)
        return render_template(
            "agents/list.html", running=running, awaiting=awaiting, finished=finished,
        )

    @app.route("/agents/new", methods=["POST"])
    def agents_new():
        prompt = request.form.get("prompt", "").strip()
        model = request.form.get("model", "").strip()
        cwd = request.form.get("cwd", "").strip()
        if not prompt:
            return redirect(url_for("agents_page"))
        runner.create_agent(prompt=prompt, model=model, cwd=cwd)
        return redirect(url_for("agents_page"))

    # --- Projects API ---
    @app.route("/api/projects", methods=["GET"])
    def api_projects_list():
        return jsonify([{"name": p.name, "path": p.path} for p in projects.list_projects()])

    @app.route("/api/projects", methods=["POST"])
    def api_projects_add():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        path = (data.get("path") or "").strip()
        if not name or not path:
            return jsonify({"error": "name and path required"}), 400
        proj = projects.add_project(name, path)
        return jsonify({"name": proj.name, "path": proj.path}), 201

    @app.route("/api/projects/<name>", methods=["DELETE"])
    def api_projects_delete(name):
        if projects.remove_project(name):
            return jsonify({"ok": True})
        return jsonify({"error": "not found"}), 404

    # --- Projects page ---
    @app.route("/projects")
    def projects_page():
        return render_template("projects/list.html", projects=projects.list_projects())

    # --- Kanban ---
    @app.route("/kanban/<project>")
    def kanban_page(project: str):
        proj = next((p for p in projects.list_projects() if p.name == project), None)
        if proj is None:
            return "Project not found", 404
        return render_template("kanban/board.html", project=proj, project_name=proj.name)

    @app.route("/api/kanban/<project>/cards", methods=["GET"])
    def api_kanban_list(project: str):
        cards = kanban.list_cards(project)
        # Refresh status from agent state for active (non-archived) cards
        for card in cards:
            if card.archived:
                continue
            if card.agent_id and card.status not in ("done", "failed", "backlog"):
                try:
                    agent = runner.load_agent(card.agent_id)
                    if agent:
                        new_status = _derive_card_status(agent)
                        if new_status != card.status:
                            kanban.update_card(project, card.id, status=new_status)
                            card.status = new_status
                except Exception:
                    pass
        from dataclasses import asdict
        return jsonify([asdict(c) for c in cards])

    @app.route("/api/kanban/<project>/cards", methods=["POST"])
    def api_kanban_create(project: str):
        data = request.get_json(force=True)
        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        if not title:
            return jsonify({"error": "title required"}), 400
        card = kanban.create_card(project, title, description)
        from dataclasses import asdict
        return jsonify(asdict(card)), 201

    @app.route("/api/kanban/<project>/cards/<card_id>", methods=["PATCH"])
    def api_kanban_update(project: str, card_id: str):
        data = request.get_json(force=True)
        allowed = {"title", "description", "status", "archived"}
        updates = {k: v for k, v in data.items() if k in allowed}
        card = kanban.update_card(project, card_id, **updates)
        if card is None:
            return jsonify({"error": "not found"}), 404
        from dataclasses import asdict
        return jsonify(asdict(card))

    @app.route("/api/kanban/<project>/cards/<card_id>", methods=["DELETE"])
    def api_kanban_delete(project: str, card_id: str):
        if kanban.delete_card(project, card_id):
            return jsonify({"ok": True})
        return jsonify({"error": "not found"}), 404

    @app.route("/api/kanban/<project>/cards/<card_id>/launch", methods=["POST"])
    def api_kanban_launch(project: str, card_id: str):
        card = kanban.get_card(project, card_id)
        if card is None:
            return jsonify({"error": "card not found"}), 404
        proj = next((p for p in projects.list_projects() if p.name == project), None)
        if proj is None:
            return jsonify({"error": "project not found"}), 404
        prompt = (
            f'## Ticket: {card.title}\n\n'
            f'{card.description}\n\n'
            f'---\n'
            f'Consignes:\n'
            f'1. Appelle LoadProjectConfig pour initialiser le projet.\n'
            f'2. Fais un diagnostic du problème ou de la feature demandée.\n'
            f'3. Propose un plan via WritePlan(user_validation_required=true) — attends la validation avant d\'implémenter.'
        )
        agent = runner.create_agent(prompt=prompt, model=app.config.get("BOUZECODE_MODEL", "claude-opus-4-6"), cwd=proj.path)
        kanban.update_card(project, card_id, status="in_progress", agent_id=agent.agent_id)
        return jsonify({"ok": True, "agent_id": agent.agent_id})

    @app.route("/api/kanban/<project>/cards/<card_id>/status", methods=["GET"])
    def api_kanban_status(project: str, card_id: str):
        card = kanban.get_card(project, card_id)
        if card is None:
            return jsonify({"error": "not found"}), 404
        if card.agent_id and card.status not in ("done", "failed", "backlog"):
            agent = runner.load_agent(card.agent_id)
            if agent:
                new_status = _derive_card_status(agent)
                if new_status != card.status:
                    kanban.update_card(project, card.id, status=new_status)
                    card.status = new_status
        return jsonify({"status": card.status, "agent_id": card.agent_id})

    def _derive_card_status(agent) -> str:
        """Map agent state to kanban card status."""
        ipc_state = runner.get_ipc_state(agent)
        ipc_status = ipc_state.get("status", "unknown")
        alive = runner.is_running(agent)
        # Check for plan validation pending
        if ipc_status == "awaiting_plan_validation":
            if not alive:
                return "done"
            return "awaiting_plan_validation"
        if ipc_status == "awaiting_input":
            has_pending = agent.session_path and web_pending.exists(agent.session_path)
            if not alive and not has_pending:
                return "done"
            return "awaiting_input"
        if not alive or ipc_status == "finished":
            if agent.returncode is not None and agent.returncode != 0:
                return "failed"
            return "done"
        return "in_progress"

    def _get_agent_for_card(project: str, card_id: str):
        """Load agent associated with a kanban card. Returns (agent, error_response)."""
        card = kanban.get_card(project, card_id)
        if card is None:
            return None, (jsonify({"error": "card not found"}), 404)
        if not card.agent_id:
            return None, (jsonify({"error": "no agent for this card"}), 404)
        agent = runner.load_agent(card.agent_id)
        if agent is None:
            return None, (jsonify({"error": "agent not found"}), 404)
        return agent, None

    @app.route("/api/kanban/<project>/cards/<card_id>/plan", methods=["GET"])
    def api_kanban_card_plan(project: str, card_id: str):
        agent, err = _get_agent_for_card(project, card_id)
        if err:
            return err
        plan_md = session_service.extract_plan_content(agent.session_path)
        if not plan_md and agent.ipc_dir:
            ipc_plan = Path(agent.ipc_dir) / "plan.md"
            if ipc_plan.exists():
                plan_md = ipc_plan.read_text(encoding="utf-8").strip() or None
        if not plan_md:
            return jsonify({"error": "no plan available"}), 404
        return jsonify({"plan_md": plan_md})

    @app.route("/api/kanban/<project>/cards/<card_id>/question", methods=["GET"])
    def api_kanban_card_question(project: str, card_id: str):
        agent, err = _get_agent_for_card(project, card_id)
        if err:
            return err
        if not agent.session_path:
            return jsonify({"error": "no session"}), 404
        pending = web_pending.load(agent.session_path)
        if not pending:
            return jsonify({"error": "no pending question"}), 404
        return jsonify({
            "question": pending.get("question", ""),
            "options": pending.get("options") or [],
            "allow_freetext": pending.get("allow_freetext", True),
        })

    @app.route("/api/kanban/<project>/cards/<card_id>/accept-plan", methods=["POST"])
    def api_kanban_card_accept_plan(project: str, card_id: str):
        agent, err = _get_agent_for_card(project, card_id)
        if err:
            return err
        model = (request.json or {}).get("model", "")
        runner.resume_auto_agent(agent, model=model)
        kanban.update_card(project, card_id, status="in_progress")
        return jsonify({"ok": True})

    @app.route("/api/kanban/<project>/cards/<card_id>/answer", methods=["POST"])
    def api_kanban_card_answer(project: str, card_id: str):
        agent, err = _get_agent_for_card(project, card_id)
        if err:
            return err
        body = request.json or {}
        answer = body.get("answer", "").strip()
        if not answer:
            return jsonify({"error": "answer is required"}), 400
        model = body.get("model", "")
        runner.resume_pending_agent(agent, answer=answer, model=model)
        kanban.update_card(project, card_id, status="in_progress")
        return jsonify({"ok": True})

    @app.route("/agents/<agent_id>")
    def agent_detail(agent_id: str):
        agent = runner.load_agent(agent_id)
        if agent is None:
            return "Agent not found", 404
        runner.refresh_agent_status(agent)
        raw_stdout, stdout_offset = runner.read_stdout(agent)
        ipc_state = runner.get_ipc_state(agent)
        alive = runner.is_running(agent)
        ipc_status = ipc_state.get("status", "unknown")
        # Reconcile stale IPC: dead process with no pending → finished.
        has_pending = agent.session_path and web_pending.exists(agent.session_path)
        if not alive and ipc_status in ("running", "awaiting_input") and not has_pending:
            ipc_status = "finished"
        return render_template(
            "agents/detail.html",
            agent=agent,
            stdout_text=_clean_stdout(raw_stdout),
            stdout_offset=stdout_offset,
            running=alive,
            ipc_status=ipc_status,
            question=ipc_state.get("question") if ipc_status in ("awaiting_input", "awaiting_plan_validation") else None,
            options=ipc_state.get("options") if ipc_status in ("awaiting_input", "awaiting_plan_validation") else None,
            has_session=bool(agent.session_path and Path(agent.session_path).exists()),
        )

    @app.route("/agents/<agent_id>/stream")
    def agent_stream(agent_id: str):
        agent = runner.load_agent(agent_id)
        if agent is None:
            return "Agent not found", 404
        offset = request.args.get("offset", 0, type=int)
        return Response(
            state_streams.generate_agent_stream(agent, initial_offset=offset),
            mimetype="text/event-stream",
        )

    @app.route("/agents/stream")
    def agents_list_stream():
        return Response(
            state_streams.generate_agents_list_stream(),
            mimetype="text/event-stream",
        )

    _PLAN_CSS = (
        "body{font-family:system-ui,-apple-system,sans-serif;max-width:800px;margin:0 auto;"
        "padding:2rem;line-height:1.6;color:#1f2328;background:#fafbfc}"
        "h1,h2,h3{color:#5e4b8a;margin:.8em 0 .4em}"
        "h1{font-size:1.5rem}h2{font-size:1.25rem}h3{font-size:1.1rem}"
        "code{background:#f0ebff;padding:2px 6px;border-radius:4px;font-size:.88em;"
        "font-family:ui-monospace,monospace;color:#5e4b8a}"
        "pre{background:#1e1e2e;color:#cdd6f4;padding:1rem;border-radius:6px;overflow-x:auto;"
        "font-family:ui-monospace,monospace;font-size:.85rem}"
        "pre code{background:none;color:inherit;padding:0}"
        "ul,ol{margin:.5em 0 .5em 1.5em}li{margin:.3em 0}"
        "strong{color:#4338ca}"
        "table{border-collapse:collapse;margin:.5em 0}"
        "th,td{border:1px solid #d1d9e0;padding:6px 12px;text-align:left}"
        "th{background:#f0ebff;font-weight:600}"
        ".empty{color:#888;padding:3rem;text-align:center;font-style:italic}"
    )

    @app.route("/agents/<agent_id>/plan")
    def agent_plan(agent_id: str):
        agent = runner.load_agent(agent_id)
        if agent is None:
            return "Agent not found", 404
        plan_md = session_service.extract_plan_content(agent.session_path)
        if not plan_md and agent.ipc_dir:
            ipc_plan = Path(agent.ipc_dir) / "plan.md"
            if ipc_plan.exists():
                plan_md = ipc_plan.read_text(encoding="utf-8").strip() or None
        if not plan_md:
            return (
                f'<!doctype html><html><head><style>{_PLAN_CSS}</style></head>'
                '<body><p class="empty">Pas de plan disponible</p></body></html>'
            )
        plan_html = md.markdown(plan_md, extensions=["fenced_code", "tables"])
        return (
            f'<!doctype html><html><head><meta charset="utf-8">'
            f'<style>{_PLAN_CSS}</style></head>'
            f'<body>{plan_html}</body></html>'
        )

    @app.route("/agents/<agent_id>/files")
    def agent_files(agent_id: str):
        agent = runner.load_agent(agent_id)
        if agent is None:
            return "Agent not found", 404
        html_content = session_service.render_edited_files(agent.session_path)
        if html_content is None:
            return (
                f'<!doctype html><html><head><style>{_PLAN_CSS}</style></head>'
                '<body><p class="empty">Aucun fichier modifie</p></body></html>'
            )
        return html_content

    @app.route("/agents/<agent_id>/session")
    def agent_session(agent_id: str):
        agent = runner.load_agent(agent_id)
        if agent is None:
            return "Agent not found", 404
        runner.refresh_agent_status(agent)
        finished = not runner.is_running(agent)
        html_content = session_service.render_session_file(agent.session_path, finished=finished)
        if html_content is None:
            return (
                f'<!doctype html><html><head><style>{_PLAN_CSS}</style></head>'
                '<body><p class="empty">Session non disponible (le processus a pu crasher avant de sauvegarder)</p></body></html>'
            )
        return html_content

    @app.route("/sessions")
    def sessions_page():
        dd = dashboard_service.get_dashboard_data()
        return render_template("sessions.html", sessions=dd.sessions)

    @app.route("/agents/<agent_id>/context")
    def agent_context(agent_id: str):
        agent = runner.load_agent(agent_id)
        if agent is None:
            return "Agent not found", 404
        html_content = context_viewer.render_context_viewer(agent.session_path)
        if html_content is None:
            return (
                f'<!doctype html><html><head><style>{_PLAN_CSS}</style></head>'
                '<body><p class="empty">Context non disponible</p></body></html>'
            )
        return html_content

    @app.route("/sessions/context")
    def session_context():
        path = request.args.get("path", "")
        if not path:
            return "Missing ?path= parameter", 400
        html_content = context_viewer.render_context_viewer(path)
        if html_content is None:
            return "Session not found or invalid", 404
        return html_content

    @app.route("/agents/<agent_id>/continue", methods=["POST"])
    def agent_continue(agent_id: str):
        agent = runner.load_agent(agent_id)
        if agent is None:
            return "Agent not found", 404
        prompt = request.form.get("prompt", "").strip()
        if not prompt:
            return redirect(url_for("agent_detail", agent_id=agent_id))
        model = request.form.get("model", "").strip()
        if agent.session_path and web_pending.exists(agent.session_path):
            runner.resume_pending_agent(agent, answer=prompt, model=model)
        else:
            runner.continue_agent(agent, prompt=prompt, model=model)
        return redirect(url_for("agent_detail", agent_id=agent.agent_id))

    @app.route("/agents/<agent_id>/resume-auto", methods=["POST"])
    def agent_resume_auto(agent_id: str):
        agent = runner.load_agent(agent_id)
        if agent is None:
            return "Agent not found", 404
        if not agent.session_path or not Path(agent.session_path).exists():
            return "Session non disponible", 400
        model = request.form.get("model", "").strip()
        runner.resume_auto_agent(agent, model=model)
        return redirect(url_for("agent_detail", agent_id=agent.agent_id))

    @app.route("/agents/<agent_id>/state")
    def agent_state(agent_id: str):
        agent = runner.load_agent(agent_id)
        if agent is None:
            return jsonify({"status": "not_found"}), 404
        return jsonify(state_streams.build_agent_state(agent))

    @app.route("/agents/<agent_id>/kill", methods=["POST"])
    def agent_kill(agent_id: str):
        agent = runner.load_agent(agent_id)
        if agent is not None:
            runner.kill_agent(agent)
            if agent.session_path and web_pending.exists(agent.session_path):
                web_pending.cancel(agent.session_path)
        return redirect(url_for("agent_detail", agent_id=agent_id))

    # --- Skills -----------------------------------------------------------

    @app.route("/skills")
    def skills_page():
        views = skills_service.list_skill_views()
        return render_template("skills/list.html", skills=views)

    @app.route("/skills/<name>")
    def skill_detail(name: str):
        view = skills_service.find_skill_view(name)
        if view is None:
            return "Skill not found", 404
        body_raw = skills_service.read_skill_file(name) if view.editable else ""
        rendered = md.markdown(body_raw, extensions=["fenced_code", "tables"]) if body_raw else ""
        return render_template(
            "skills/detail.html",
            view=view,
            body_raw=body_raw,
            rendered=rendered,
        )

    @app.route("/skills/<name>/save", methods=["POST"])
    def skill_save(name: str):
        content = request.form.get("content", "")
        ok = skills_service.write_skill_file(name, content)
        if not ok:
            return jsonify({"ok": False, "error": "not editable"}), 400
        return redirect(url_for("skill_detail", name=name))

    # --- Tools ------------------------------------------------------------

    @app.route("/tools")
    def tools_page():
        views = tools_service.list_tool_views()
        return render_template("tools/list.html", tools=views)

    # --- Todo Notepad (per-project) ----------------------------------------

    @app.route("/todo/<project>")
    def todo_page(project: str):
        proj = next((p for p in projects.list_projects() if p.name == project), None)
        if proj is None:
            return "Project not found", 404
        content = todo.load(project)
        return render_template("todo.html", content=content, project_name=project, project_path=proj.path)

    @app.route("/api/todo/<project>", methods=["GET"])
    def api_todo_get(project: str):
        return jsonify({"content": todo.load(project)})

    @app.route("/api/todo/<project>", methods=["PUT"])
    def api_todo_put(project: str):
        data = request.get_json(force=True)
        todo.save(project, data.get("content", ""))
        return jsonify({"ok": True})

    return app


_shutdown_done = False
_GRACEFUL_TIMEOUT = 3  # seconds to wait for agents to self-save


def _graceful_shutdown() -> None:
    """Signal all running agents to save and exit, wait, then force-terminate survivors."""
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True

    import psutil
    agents = runner.list_agents()
    running = [a for a in agents if a.returncode is None and psutil.pid_exists(a.pid)]
    if not running:
        return

    print(f"\n[bouzequi] Graceful shutdown: signaling {len(running)} running agent(s)...")
    for agent in running:
        runner.graceful_cancel_agent(agent)

    deadline = time.time() + _GRACEFUL_TIMEOUT
    while time.time() < deadline:
        still_alive = [a for a in running if psutil.pid_exists(a.pid)]
        if not still_alive:
            break
        time.sleep(0.3)

    for agent in running:
        if psutil.pid_exists(agent.pid):
            try:
                psutil.Process(agent.pid).terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        runner.refresh_agent_status(agent)

    print(f"[bouzequi] Shutdown complete — {len(running)} agent(s) stopped.")


def _shutdown_signal_handler(signum, frame):
    _graceful_shutdown()
    raise SystemExit(0)


def main() -> None:
    parser = argparse.ArgumentParser(prog="bouzequi", description="BouzéqUI Flask web interface")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5055)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    atexit.register(_graceful_shutdown)
    signal.signal(signal.SIGINT, _shutdown_signal_handler)

    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
