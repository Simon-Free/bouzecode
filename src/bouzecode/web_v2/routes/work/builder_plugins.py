# [desc] API agent-builder (suite) : plugins (Artifactory, repo GitLab ou dossier git local), catalogue d'agents installés / disponibles, export / import YAML d'un agent. [/desc]
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ...services import agent_catalog as agent_catalog_svc
from ...services import agent_share
from ...services import plugins as plugins_svc
from .._body import json_body
from .._errors import erreur

builder_plugins_bp = Blueprint("builder_plugins_api", __name__)


def _resultat(result, code: str):
    """Un service qui rend une chaîne a refusé : 400 `code`, le message tel quel."""
    if isinstance(result, str):
        return erreur(code, result, 400)
    return jsonify(result)


@builder_plugins_bp.get("/api/plugins")
def api_list_plugins():
    """plugins installés → {plugins:[{name, package, version, scope, source, enabled, description,
    tools}]}"""
    return jsonify({"plugins": plugins_svc.list_installed()})


@builder_plugins_bp.post("/api/plugins")
def api_install_plugin():
    """{package, source?, confirm_git?} — installer un plugin (Artifactory par nom, ou source
    git/local). 400 `installation_refusee`."""
    payload = json_body(request)
    return _resultat(plugins_svc.install(payload.get("package", ""), payload.get("source"),
                                         confirm_git=bool(payload.get("confirm_git"))),
                     "installation_refusee")


@builder_plugins_bp.post("/api/plugins/from-gitlab")
def api_install_plugin_from_gitlab():
    """{input, confirm_git?} — installer un plugin depuis une URL de repo GitLab OU un dossier git
    local (Artifactory d'abord, repo git en fallback confirmé). 400 `source_requise` /
    `installation_refusee`."""
    payload = json_body(request)
    raw = (payload.get("input") or "").strip()
    if not raw:
        return erreur("source_requise", "URL GitLab ou chemin d'un dossier git local requis", 400)
    return _resultat(plugins_svc.from_gitlab(raw, confirm_git=bool(payload.get("confirm_git"))),
                     "installation_refusee")


@builder_plugins_bp.get("/api/agents/catalog")
def api_agents_catalog():
    """{installed:[...], available:[...]} — parité avec la CLI /agent."""
    return jsonify(agent_catalog_svc.catalog_view())


@builder_plugins_bp.post("/api/agents/install")
def api_agents_install():
    """{name} — installe localement un profil du catalogue (YAML + plugins requis). 422
    `installation_impossible` (details.errors) : jamais un 200 qu'une UI prendrait pour un
    succès."""
    result = agent_catalog_svc.install(json_body(request).get("name", ""))
    if not result.get("ok"):
        errors = result.get("errors") or ["installation impossible"]
        return erreur("installation_impossible", " ; ".join(errors), 422, errors=errors)
    return jsonify(result)


@builder_plugins_bp.post("/api/agents/catalog/refresh")
def api_agents_catalog_refresh():
    """Relit le catalogue DISTANT et rend la vue fraîche. 502 `catalogue_injoignable` si le
    distant ne répond pas (pas de remote, hors ligne) : la vue en cache reste dans
    `error.details` (installed, available), l'UI continue de l'afficher."""
    try:
        return jsonify(agent_catalog_svc.refresh())
    except Exception as exc:  # noqa: BLE001 — panne git/réseau rendue en 502, l'UI reste vivante
        return erreur("catalogue_injoignable",
                      f"rafraîchissement du catalogue impossible : {exc}", 502,
                      **agent_catalog_svc.catalog_view())


@builder_plugins_bp.post("/api/agents/<name>/upgrade-plugins")
def api_upgrade_agent_plugins(name: str):
    """{confirm_git?} — réinstalle/met à jour les plugins dont dépend un profil d'agent. 404
    `profil_inconnu`."""
    result = plugins_svc.upgrade_profile_plugins(
        name, confirm_git=bool(json_body(request).get("confirm_git")))
    if "error" in result:
        return erreur("profil_inconnu", str(result["error"]), 404)
    return jsonify(result)


@builder_plugins_bp.get("/api/agents/<name>/export")
def api_export_agent(name: str):
    """exporte un agent/profil sous forme de YAML partageable → {name, yaml}. 404
    `agent_inconnu`."""
    text = agent_share.export_agent(name)
    if text is None:
        return erreur("agent_inconnu", f"agent inconnu : {name}", 404)
    return jsonify({"name": name, "yaml": text})


@builder_plugins_bp.post("/api/agents/import")
def api_import_agent():
    """{yaml, confirm_git?} — importe un agent/profil depuis le YAML produit par
    /api/agents/<name>/export. 400 `import_refuse`."""
    payload = json_body(request)
    return _resultat(agent_share.import_agent(payload.get("yaml", ""),
                                              confirm_git=bool(payload.get("confirm_git"))),
                     "import_refuse")
