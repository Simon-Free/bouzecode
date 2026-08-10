# [desc] Factory Flask web_v2: pages serveur (conversations/session/agent-builder) + /api/schema dérivé de url_map. Port 5056. [/desc]
"""BouzéqUI v2 — `python -m bouzecode.web_v2` ou entry point `bouzequi2`. Voir SPEC.md."""
from __future__ import annotations

import argparse
import inspect
import os
import re
from pathlib import Path

from flask import Flask, redirect, render_template

from . import startup
from .api_descriptions import ENDPOINT_DESCRIPTIONS
from .routes import register_routes

_BASE = Path(__file__).parent

# --------------------------------------------------------------------------------
# Cache navigateur du statique
# --------------------------------------------------------------------------------
# L'ancien réglage `SEND_FILE_MAX_AGE_DEFAULT = 0  # no browser cache for dev` n'était
# pas tenable : il s'appliquait à TOUT le statique, dont `static/vendor/monaco/` (copie
# figée de monaco-editor 0.52.0, ~1000 fichiers dont un `tsWorker.js` de 47 000 lignes),
# et forçait donc le navigateur à redemander l'éditeur entier à chaque chargement de
# `/sessions/<key>`. Le commentaire disait « for dev », mais `main()` appelle
# toujours `create_app()` : il n'existe pas d'autre chemin d'exécution.
#
# Correctif retenu : une durée de cache DIFFÉRENCIÉE PAR CHEMIN, la plus simple des deux
# directions possibles — elle ne demande aucune empreinte d'URL à maintenir sur les
# assets maison, qui restent servis tels quels sous leur nom stable.
#   `vendor/**`   → cache long : ces fichiers sont tiers et immuables (on ne les édite
#                   jamais à la main ; une montée de version se fait par re-vendorisation).
#   tout le reste → `no-cache` : le navigateur revalide à chaque fois, donc une édition
#                   de `css/` ou `js/` est visible au simple rechargement, mais un fichier
#                   inchangé coûte un 304 vide au lieu d'un re-téléchargement complet.
VENDOR_MAX_AGE_SECONDS = 30 * 24 * 3600


class VendorCachingFlask(Flask):
    """Flask dont la durée de cache navigateur dépend du chemin de l'asset statique."""

    def get_send_file_max_age(self, filename: str | None) -> int | None:
        if filename and filename.replace("\\", "/").startswith("vendor/"):
            return VENDOR_MAX_AGE_SECONDS
        return None  # no-cache → revalidation conditionnelle (304), pas de re-download


# --------------------------------------------------------------------------------
# Schéma d'API (contrat P7 : « un LLM consomme le serveur »)
# --------------------------------------------------------------------------------
SCHEMA_DESCRIPTION = (
    "BouzéqUI v2 — API JSON consommable par un LLM. Lecture: GET; actions: POST. "
    "Schéma DÉRIVÉ de app.url_map : il liste exactement les routes /api/ enregistrées."
)

_CONVERTER_PREFIX = re.compile(r"<[^:>]+:([^>]+)>")
_NON_API_METHODS = frozenset({"HEAD", "OPTIONS"})


def schema_key(rule: str, method: str) -> str:
    """Clé canonique d'un endpoint : « POST /api/tickets/<slug>/<ticket_id>/done »."""
    canonical_rule = _CONVERTER_PREFIX.sub(r"<\1>", rule)
    return f"{method} {canonical_rule}"


def docstring_summary(view) -> str:
    """Premier paragraphe du docstring d'une vue, replié sur une ligne ('' si absent)."""
    doc = inspect.getdoc(view) or ""
    return " ".join(doc.split("\n\n", 1)[0].split())


def build_api_schema(app: Flask) -> dict:
    """Schéma des routes `/api/` DÉRIVÉ de `app.url_map` — jamais saisi à la main.

    Une entrée par couple (méthode, règle) réellement enregistré. La description vient
    de `ENDPOINT_DESCRIPTIONS` si elle y figure, sinon du docstring de la vue, sinon elle
    est vide : une description vide vaut mieux qu'une description fausse.
    """
    endpoints = {}
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/"):
            continue
        view = app.view_functions[rule.endpoint]
        for method in sorted(rule.methods - _NON_API_METHODS):
            key = schema_key(rule.rule, method)
            endpoints[key] = ENDPOINT_DESCRIPTIONS.get(key) or docstring_summary(view)
    return {"description": SCHEMA_DESCRIPTION, "endpoints": dict(sorted(endpoints.items()))}


def create_app() -> Flask:
    app = VendorCachingFlask(
        "bouzecode_web_v2",
        template_folder=str(_BASE / "templates"),
        static_folder=str(_BASE / "static"),
    )
    # Pick up extra .bouzecode dirs the user registered (legacy substrate; the UI
    # now installs plugin packages from GitLab instead — see /api/plugins/from-gitlab).
    from ..backend.core.paths import register_persisted_extra_dirs
    register_persisted_extra_dirs()
    # Fige SHA + version bouzecode EN MÉMOIRE dès le boot : les merges de la flotte
    # dans develop ne pourront plus faire bouger la version de référence du process.
    from . import version as _version
    _version.capture_boot_state()
    # Sanity-check de l'env API au boot : si le serveur a été relancé hors
    # bouzeui.ps1 (ANTHROPIC_BASE_URL/clé absentes ou base_url injoignable), on
    # fige un verdict KO consommé par le bandeau UI rouge + les guards 503 des
    # endpoints de spawn. Empêche le « serveur up mais tous les agents meurent
    # en silence ». Fail-safe : ne bloque jamais le boot.
    from . import api_sanity as _api_sanity
    _api_sanity.capture_api_sanity()
    register_routes(app)

    # Migration one-shot au boot : rattache les sous-agents hérités (validateur /
    # résolveur de merge) créés AVANT le fix 4c8c410 — parent littéral
    # "dispatcher:validate"/"dispatcher:auto-merge" — à l'id réel de leur codeur (run
    # 'work' du même ticket). Idempotente, loggée, non destructive ; un échec ne doit
    # jamais empêcher le serveur de démarrer.
    try:
        from .services.work import migrations
        migrations.migrate_orphan_validators()
    except Exception:  # noqa: BLE001 — migration best-effort, ne bloque pas le boot
        import logging
        logging.getLogger(__name__).exception("migrate_orphan_validators a échoué au boot")

    # Migration one-shot au boot : les tickets laissés en vol par la chaîne automatique
    # (retirée, cf. docs/design_p10_orchestration.md) n'ont plus aucune transition qui
    # matche et resteraient « en cours » à vie. Ils repassent « à relire », avec un
    # commentaire d'explication. Idempotente, loggée, non destructive.
    try:
        from .services.work import migrations
        migrations.migrate_inflight_tickets()
    except Exception:  # noqa: BLE001 — migration best-effort, ne bloque pas le boot
        import logging
        logging.getLogger(__name__).exception("migrate_inflight_tickets a échoué au boot")

    # Plus aucune chaîne automatique : le hook on_completion ne fait que clore le run.
    # `start_poller` arme le WATCHDOG (reconciler crash-aware), ACTIF PAR DÉFAUT : c'est
    # le chemin nominal des CRASHES (agent mort / hook non-firé), le seul automatisme
    # conservé. Opt-out via BOUZECODE_WAKE_POLLER=0.
    from .services.work import wake
    wake.start_poller()

    @app.get("/")
    def home_page():
        return redirect("/conversations")

    @app.get("/sessions")
    def sessions_redirect():
        return redirect("/")

    @app.get("/sessions/<path:key>")
    def session_page(key: str):
        return render_template("session.html", page="home", session_key=key)

    @app.get("/conversations")
    def conversations_page():
        return render_template("conversations.html", page="conversations")

    @app.get("/agent-builder")
    def agent_builder_page():
        return render_template("agent_builder.html", page="agents")

    @app.get("/api/schema")
    def api_schema():
        """ce schéma : toutes les routes /api/ du serveur, dérivées de app.url_map"""
        return build_api_schema(app)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="BouzéqUI v2 — UI web bouzecode")
    parser.add_argument("--port", type=int, default=5056)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    startup.fail_if_port_taken(args.host, args.port)
    # Un serveur hérité en mode debug peut exporter ces vars ; laissées en place,
    # werkzeug croit être un enfant reloader et se dédouble. On les purge pour
    # garantir UN seul process, sans rechargement dynamique (cf. TODO #4).
    for _v in ("WERKZEUG_SERVER_FD", "WERKZEUG_RUN_MAIN"):
        os.environ.pop(_v, None)
    # Base URL that spawned agents' on_completion hooks POST back to. Default in the
    # hook is 127.0.0.1:5056; set it here so a non-default port still resolves.
    host = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
    os.environ.setdefault("BOUZECODE_WEB_BASE_URL", f"http://{host}:{args.port}")
    startup.reconcile_boot_state()
    create_app().run(host=args.host, port=args.port, debug=args.debug,
                     use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
