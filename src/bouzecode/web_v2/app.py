# [desc] Factory Flask web_v2 : pages serveur (bureau, conversations, agent-builder), enregistrement des routes (dont /api/schema, dérivé de url_map), boot. Port 5056. [/desc]
"""bouzeui v2 — `python -m bouzecode.web_v2` ou entry point `bouzeui2`. Voir SPEC.md."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from flask import Flask, redirect, render_template

from . import startup
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
    # Jeton local exigé sur toute mutation /api/ + corps JSON obligatoire (spec ticketing B8).
    from . import securite
    securite.installer(app)
    from . import compression
    compression.installer(app)


    # Migrations de boot des stores (tickets L2, runs validate hérités, tâches du Bureau). Un
    # store du VRAI HOME n'est migré que par le serveur de référence (`main`) : un `create_app()`
    # lancé par un script d'agent l'a migré le 2026-10-06 avec le code d'un worktree.
    from . import migrations_au_boot
    migrations_au_boot.jouer()

    # Plus aucune chaîne automatique : le hook on_completion ne fait que clore le run.
    # `start_poller` arme le WATCHDOG (reconciler crash-aware), ACTIF PAR DÉFAUT : c'est
    # le chemin nominal des CRASHES (agent mort / hook non-firé), le seul automatisme
    # conservé. Opt-out via BOUZECODE_WAKE_POLLER=0.
    from .services.work import wake
    wake.start_poller()

    # Teams est en LECTURE SEULE : seul l'outil `Teams` de l'agent le sollicite, à la
    # demande. L'ancien pont vers le chat (sonnette, sondage, abonnement Graph) a été
    # retiré : l'écriture dans Teams est obsolète.

    @app.context_processor
    def lexique_des_pages():
        """Le lexique UNIQUE (services/work/lexique.py), injecté dans chaque page (`base.html`)."""
        from .services.work import lexique
        return {"lexique_json": json.dumps(lexique.table(), ensure_ascii=False).replace("</", "<\\/")}

    @app.get("/")
    def home_page():
        """Le Bureau est la page d'accueil (SPEC §0) : ce qui m'attend, puis mon travail."""
        return redirect("/bureau")

    @app.get("/sessions")
    def sessions_redirect():
        return redirect("/conversations")

    @app.get("/sessions/<path:key>")
    def session_page(key: str):
        """Ancienne vue détaillée d'une session : ses onglets (Fichiers, Coûts & tours) vivent
        désormais dans le panneau d'un agent de /conversations."""
        from urllib.parse import quote

        agent = key[len("agent/"):] if key.startswith("agent/") else key
        return redirect(f"/conversations?agent={quote(agent, safe='')}")

    @app.get("/conversations")
    def conversations_page():
        return render_template("conversations.html", page="conversations")

    @app.get("/bureau")
    def bureau_page():
        return render_template("bureau.html", page="bureau")

    @app.get("/agent-builder")
    def agent_builder_page():
        return render_template("agent_builder.html", page="agents")

    @app.get("/todo")
    def todo_page():
        """l'ancienne page TO-DO : l'URL reste valide mais le Bureau la porte

        Un seul onglet pour un seul geste : la TO-DO est devenue une SECTION du
        Bureau. On garde l'URL (liens, favoris, schéma d'API) en l'emmenant là où
        la matière vit maintenant, au lieu de servir un second onglet concurrent."""
        from flask import redirect

        return redirect("/bureau", code=302)

    @app.get("/_ds")
    def design_system_page():
        """Démo du design system (hors navigation) : tous les composants de ds.css / lib/ui.js."""
        return render_template("_ds.html", page="ds")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="bouzeui v2 — UI web bouzecode")
    parser.add_argument("--port", type=int, default=5056)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    startup.fail_if_port_taken(args.host, args.port)
    from . import securite
    avertissement = securite.avertir_si_hote_expose(args.host)
    if avertissement:
        print(avertissement, flush=True)
    # Un serveur hérité en mode debug peut exporter ces vars ; laissées en place,
    # werkzeug croit être un enfant reloader et se dédouble. On les purge pour
    # garantir UN seul process, sans rechargement dynamique (cf. TODO #4).
    for _v in ("WERKZEUG_SERVER_FD", "WERKZEUG_RUN_MAIN"):
        os.environ.pop(_v, None)
    # Base URL that spawned agents' on_completion hooks POST back to. Default in the
    # hook is 127.0.0.1:5056; set it here so a non-default port still resolves.
    host = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
    os.environ.setdefault("BOUZECODE_WEB_BASE_URL", f"http://{host}:{args.port}")
    # Seul le serveur de RÉFÉRENCE du parc (verrou OS exclusif, cf. `reference`) agit seul sur
    # la flotte : watchdog, ménage du pool chaud, réconciliation et reprise au boot. Un second
    # serveur (smoke d'un agent sur un autre port) sert l'interface mais reste PASSIF.
    from . import reference
    from .services.work import warm_pool
    if reference.acquerir(args.port):
        warm_pool.SERVEUR_PRINCIPAL = True
        startup.reconcile_boot_state()
    else:
        print(startup.message_instance_passive(reference.detenteur()), flush=True)
    app = create_app()
    from . import prechauffage
    prechauffage.lancer()
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
