# [desc] API agent-builder (global) : catalogue tools/skills/hooks, CRUD des profils ~/.bouzecode, et installation de plugins (index de paquets ou depuis un repo GitLab / dossier git local). [/desc]
from __future__ import annotations

from flask import Blueprint, jsonify, request

from .._body import json_body

from ...services import profiles as profiles_svc
from ...services import skills as skills_svc
from ...services import plugins as plugins_svc
from ...services import agent_share
from ...services import agent_catalog as agent_catalog_svc

builder_bp = Blueprint("builder_api", __name__)


@builder_bp.get("/api/builder/catalog")
def api_builder_catalog():
    return jsonify(profiles_svc.catalog())


@builder_bp.get("/api/builder/agents")
def api_builder_agents():
    """All existing agents/profiles (every source) for the browse-and-edit panel."""
    return jsonify({"agents": profiles_svc.list_agents()})


@builder_bp.post("/api/builder/preview")
def api_builder_preview():
    """Full computed system prompt for the current selections (read-only view)."""
    return jsonify(profiles_svc.preview_prompt(json_body(request)))


@builder_bp.get("/api/profiles")
def api_list_profiles():
    return jsonify({"profiles": profiles_svc.list_profiles()})


@builder_bp.get("/api/profiles/<name>")
def api_get_profile(name: str):
    profile = profiles_svc.get_profile(name)
    if profile is None:
        return jsonify({"error": f"profil inconnu: {name}"}), 404
    return jsonify(profile)


@builder_bp.post("/api/profiles")
def api_save_profile():
    result = profiles_svc.save_profile(json_body(request))
    if isinstance(result, str):
        return jsonify({"error": result}), 400
    return jsonify(result)


@builder_bp.delete("/api/profiles/<name>")
def api_delete_profile(name: str):
    if not profiles_svc.delete_profile(name):
        return jsonify({"error": f"profil inconnu: {name}"}), 404
    return jsonify({"ok": True})


# ── Plugins ───────────────────────────────────────────────────────────────────

@builder_bp.get("/api/plugins")
def api_list_plugins():
    return jsonify({"plugins": plugins_svc.list_installed()})


@builder_bp.post("/api/plugins")
def api_install_plugin():
    payload = json_body(request)
    result = plugins_svc.install(
        payload.get("package", ""),
        payload.get("source"),
        confirm_git=bool(payload.get("confirm_git")),
    )
    if isinstance(result, str):
        return jsonify({"error": result}), 400
    return jsonify(result)


# ── Agent catalog (installés vs disponibles) ───────────────────────────────────

@builder_bp.get("/api/agents/catalog")
def api_agents_catalog():
    """{installed:[...], available:[...]} — parité avec la CLI /agent."""
    return jsonify(agent_catalog_svc.catalog_view())


@builder_bp.post("/api/agents/install")
def api_agents_install():
    """Install a catalog profile locally (write YAML + ensure plugins)."""
    name = (json_body(request)).get("name", "")
    return jsonify(agent_catalog_svc.install(name))


@builder_bp.post("/api/agents/catalog/refresh")
def api_agents_catalog_refresh():
    """Force-refresh the remote catalog, return the fresh view.

    Best-effort: a fetch failure (no remote, offline) is surfaced in ``errors``
    but never turns into a 500 — the current cached view is still returned.
    """
    try:
        return jsonify(agent_catalog_svc.refresh())
    except Exception as exc:  # noqa: BLE001 — surface git/network failure, keep UI alive
        view = agent_catalog_svc.catalog_view()
        view["errors"] = [str(exc)]
        view["ok"] = False
        return jsonify(view)


# ── Agent export / import ──────────────────────────────────────────────────────

@builder_bp.post("/api/agents/<name>/upgrade-plugins")
def api_upgrade_agent_plugins(name: str):
    payload = json_body(request)
    result = plugins_svc.upgrade_profile_plugins(
        name,
        confirm_git=bool(payload.get("confirm_git")),
    )
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@builder_bp.get("/api/agents/<name>/export")
def api_export_agent(name: str):
    text = agent_share.export_agent(name)
    if text is None:
        return jsonify({"error": f"agent inconnu: {name}"}), 404
    return jsonify({"name": name, "yaml": text})


@builder_bp.post("/api/agents/import")
def api_import_agent():
    payload = json_body(request)
    result = agent_share.import_agent(
        payload.get("yaml", ""),
        confirm_git=bool(payload.get("confirm_git")),
    )
    if isinstance(result, str):
        return jsonify({"error": result}), 400
    return jsonify(result)


@builder_bp.get("/api/skills")
def api_list_skills():
    return jsonify({"skills": skills_svc.list_skills()})


@builder_bp.get("/api/skills/<name>")
def api_get_skill(name: str):
    if request.args.get("new"):
        return jsonify(skills_svc.new_skill_template(name))
    skill = skills_svc.get_skill(name)
    if skill is None:
        return jsonify({"error": f"skill inconnue: {name}"}), 404
    return jsonify(skill)


@builder_bp.post("/api/skills")
def api_save_skill():
    payload = json_body(request)
    result = skills_svc.save_skill(payload.get("name", ""), payload.get("content", ""))
    if isinstance(result, str):
        return jsonify({"error": result}), 400
    return jsonify(result)


@builder_bp.delete("/api/skills/<name>")
def api_delete_skill(name: str):
    if not skills_svc.delete_skill(name):
        return jsonify({"error": f"skill globale inconnue: {name}"}), 404
    return jsonify({"ok": True})


# ── Installer un plugin depuis GitLab (remplace les ex-"chemins .bouzecode") ───

@builder_bp.post("/api/plugins/from-gitlab")
def api_install_plugin_from_gitlab():
    """Install a plugin from a GitLab repo URL or a local git folder path.
    the private package index (pip name) first; the repo git source is a confirmed fallback."""
    payload = json_body(request)
    raw = (payload.get("input") or "").strip()
    if not raw:
        return jsonify({"error": "URL GitLab ou chemin d'un dossier git local requis"}), 400
    result = plugins_svc.from_gitlab(raw, confirm_git=bool(payload.get("confirm_git")))
    if isinstance(result, str):
        return jsonify({"error": result}), 400
    return jsonify(result)
