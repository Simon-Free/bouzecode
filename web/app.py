# [desc] BouzéGUI Flask web application providing UI routes for managing agents, skills, and tools. [/desc]
"""BouzéGUI Flask app — main web interface for bouzecode."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import markdown as md
from flask import Flask, Response, jsonify, redirect, render_template, request, url_for

from web import dashboard_service, pending as web_pending, runner, session_service, skills_service, state_streams, tools_service

from web.stdout_filter import clean_stdout as _clean_stdout


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )

    # Respawn agents that were killed when the server last stopped
    resumed = runner.resume_interrupted_agents()
    if resumed:
        print(f"[bouzegui] Resumed {len(resumed)} interrupted agent(s): "
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
            ipc_status = runner.get_ipc_state(agent).get("status")
            if ipc_status == "awaiting_input":
                awaiting.append(agent)
            elif not runner.is_running(agent) or ipc_status == "finished":
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

    @app.route("/agents/<agent_id>")
    def agent_detail(agent_id: str):
        agent = runner.load_agent(agent_id)
        if agent is None:
            return "Agent not found", 404
        runner.refresh_agent_status(agent)
        raw_stdout, _ = runner.read_stdout(agent)
        ipc_state = runner.get_ipc_state(agent)
        alive = runner.is_running(agent)
        ipc_status = ipc_state.get("status", "unknown")
        # Reconcile stale IPC: dead process with no pending → finished
        has_pending = agent.session_path and web_pending.exists(agent.session_path)
        if not alive and ipc_status in ("running", "awaiting_input") and not has_pending:
            ipc_status = "finished"
        return render_template(
            "agents/detail.html",
            agent=agent,
            stdout_text=_clean_stdout(raw_stdout),
            running=alive,
            ipc_status=ipc_status,
            question=ipc_state.get("question") if ipc_status == "awaiting_input" else None,
            options=ipc_state.get("options") if ipc_status == "awaiting_input" else None,
            has_session=bool(agent.session_path and Path(agent.session_path).exists()),
        )

    @app.route("/agents/<agent_id>/stream")
    def agent_stream(agent_id: str):
        agent = runner.load_agent(agent_id)
        if agent is None:
            return "Agent not found", 404
        return Response(
            state_streams.generate_agent_stream(agent),
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

    return app


def main() -> None:
    parser = argparse.ArgumentParser(prog="bouzegui", description="BouzéGUI Flask web interface")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5055)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
