# [desc] Factory Flask web_v2: pages serveur (home/projet/session/fichiers) + /api/schema. Port 5056. [/desc]
"""BouzéqUI v2 — `python -m bouzecode.web_v2` ou entry point `bouzequi2`. Voir SPEC.md."""
from __future__ import annotations

import argparse
import socket
from pathlib import Path

from flask import Flask, abort, redirect, render_template

from .routes import register_routes
from .services.work import projects, tickets

_BASE = Path(__file__).parent

API_SCHEMA = {
    "description": "BouzéqUI v2 — API JSON consommable par un LLM. Lecture: GET; actions: POST.",
    "endpoints": {
        "GET /api/projects": "projets ouverts + compteurs (agents en cours/en attente, tickets à relire, validations KO)",
        "POST /api/projects {name, path}": "ouvrir un projet",
        "GET /api/projects/<slug>/agents": "agents web du projet avec statut live",
        "GET /api/projects/<slug>/tickets": "tickets du projet (status dérivé, runs avec verdicts, commentaires)",
        "POST /api/projects/<slug>/tickets {title, prompt, model?, typology?, launch?}": "créer un ticket (typology applique un profil agent)",
        "POST /api/tickets/<slug>/<id>/launch {model?}": "relancer un agent de travail sur le ticket",
        "POST /api/tickets/<slug>/<id>/validate {kind: tests|refacto, model?}": "lancer une validation, verdict parsé (VERDICT: OK|KO)",
        "POST /api/tickets/<slug>/<id>/comments {text, send?}": "commenter; send=true relance l'agent avec le commentaire",
        "POST /api/tickets/<slug>/<id>/done": "basculer terminé",
        "GET /api/tickets/<slug>/<id>/results": "MR/PR détectées dans la session, branche git, commits depuis création, fichiers modifiés",
        "GET /api/sessions": "agents web + sessions CLI récentes",
        "GET /api/sessions/grep?q=<regex>&day=&model=&role=&limit=50": "recherche transversale regex dans toutes les sessions (messages + tool_calls)",
        "GET /api/sessions/<key>/blocks?after=N&plain=1": "conversation; plain=1 → texte structuré sans HTML",
        "GET /api/sessions/<key>/turns": "par appel LLM: heure, delta_s, tokens in/out, cache lu/écrit, %hit, outils, coût",
        "GET /api/sessions/<key>/costs": "agrégats coûts session: par modèle + total (tokens in/out, cache lu/écrit, %hit, coût $)",
        "GET /api/sessions/<key>/turns/<n>": "payload exact du tour, items annotés cached/new-cache/fresh + réponse",
        "GET /api/sessions/<key>/files": "diffs des fichiers modifiés (file_snapshots)",
        "GET /api/typologies?project=<slug>": "typologies d'agents déclarées (projet + global)",
        "POST /api/classify {prompt, project_slug?}": "classification auto du prompt → {title, project_slug, typology}",
        "POST /api/agents/launch {prompt, model?, cwd?, typology?}": "lancer un agent libre (typology applique un profil)",
        "POST /api/agents/<id>/continue {text}": "follow-up ou réponse à une question",
        "POST /api/agents/<id>/kill": "tuer l'agent",
        "GET /api/files/tree?root=<slug>&path=": "arborescence (racine = projet ouvert ou défaut serveur)",
        "GET /api/files/content?root=<slug>&path=&hl=1": "contenu fichier; hl=1 → HTML pygments",
        "GET /api/models": "modèles disponibles (menu déroulant)",
    },
}


def create_app() -> Flask:
    app = Flask(
        "bouzecode_web_v2",
        template_folder=str(_BASE / "templates"),
        static_folder=str(_BASE / "static"),
    )
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # no browser cache for dev
    register_routes(app)

    @app.get("/")
    def home_page():
        return render_template("home.html", page="home", projects=projects.overview())

    @app.get("/p/<slug>")
    def project_page(slug: str):
        project = projects.find(slug)
        if project is None:
            abort(404)
        rows = tickets.list_tickets(slug, refresh=True)
        for ticket in rows:
            ticket["status"] = tickets.derive_status(ticket)
        return render_template("project.html", page="home", project=project, tickets=rows)

    @app.get("/sessions")
    def sessions_redirect():
        return redirect("/")

    @app.get("/sessions/<path:key>")
    def session_page(key: str):
        return render_template("session.html", page="home", session_key=key)

    @app.get("/files")
    def files_page():
        return render_template("files.html", page="files", projects=projects.list_projects())

    @app.get("/api/schema")
    def api_schema():
        return API_SCHEMA

    return app


def fail_if_port_taken(host: str, port: int) -> None:
    """Le dev server Flask bind avec SO_REUSEADDR : sous Windows deux serveurs
    peuvent se lier au même port en silence (agents fantômes, courses sur les
    caches, env différents selon l'instance qui répond). Bind exclusif de test
    pour refuser le démarrage si une instance écoute déjà."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if exclusive is not None:
        sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
    try:
        sock.bind((host, port))
    except OSError as exc:
        raise SystemExit(
            f"web_v2: le port {port} est déjà servi par une autre instance — "
            f"arrête-la d'abord (Get-NetTCPConnection -LocalPort {port})."
        ) from exc
    finally:
        sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="BouzéqUI v2 — UI web bouzecode")
    parser.add_argument("--port", type=int, default=5056)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    fail_if_port_taken(args.host, args.port)
    create_app().run(host=args.host, port=args.port, debug=args.debug, threaded=True)
