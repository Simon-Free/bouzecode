# [desc] API agent-builder (global) : catalogue tools/skills/hooks, aperçu du prompt, CRUD des profils et des skills ~/.bouzecode. Les plugins et le catalogue d'agents sont dans `builder_plugins.py`. [/desc]
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ...services import profiles as profiles_svc
from ...services import skills as skills_svc
from .._body import json_body
from .._errors import erreur

builder_bp = Blueprint("builder_api", __name__)


@builder_bp.get("/api/builder/catalog")
def api_builder_catalog():
    """catalogue agent-builder → {tools:[{name, description, read_only, system}], skills:[{name,
    description, source}], hooks:[{name, description}], plugins:[{name, package, version, scope,
    source, enabled, description, tools}]}"""
    return jsonify(profiles_svc.catalog())


@builder_bp.get("/api/builder/agents")
def api_builder_agents():
    """tous les agents/profils existants (toutes sources) → {agents:[{name, kind, source, editable,
    description, model, tools, skills, hooks, system_prompt_extra, requires_plugins}]}"""
    return jsonify({"agents": profiles_svc.list_agents()})


@builder_bp.post("/api/builder/preview")
def api_builder_preview():
    """{system_prompt_extra?, model?, tools?, skills?, hooks?} — system prompt complet calculé
    (lecture seule) + bits runtime (tools/hooks/skills)"""
    return jsonify(profiles_svc.preview_prompt(json_body(request)))


@builder_bp.get("/api/profiles")
def api_list_profiles():
    """profils d'agent globaux (~/.bouzecode/profiles/*.yaml), accessibles partout →
    {profiles:[{name, description, model, tools, skills, hooks, system_prompt_extra,
    requires_plugins}]}"""
    return jsonify({"profiles": profiles_svc.list_profiles()})


@builder_bp.get("/api/profiles/<name>")
def api_get_profile(name: str):
    """détail d'un profil d'agent → {name, description, model, tools, skills, hooks,
    system_prompt_extra, requires_plugins}. 404 `profil_inconnu`."""
    profile = profiles_svc.get_profile(name)
    if profile is None:
        return erreur("profil_inconnu", f"profil inconnu : {name}", 404)
    return jsonify(profile)


@builder_bp.post("/api/profiles")
def api_save_profile():
    """{name, tools?, skills?, hooks?, model?, system_prompt_extra?, create?, based_on?} —
    créer/écraser un profil d'agent global (`name` seul est obligatoire ; les listes se donnent
    par nom, cf. GET /api/builder/catalog). `create:true` → 409 `exists` si le nom est pris ;
    `based_on` → les sélections introuvables du profil dupliqué sont conservées. 400
    `profil_invalide`."""
    try:
        result = profiles_svc.save_profile(json_body(request))
    except profiles_svc.ProfileExists as exc:
        return erreur("exists", str(exc), 409)
    if isinstance(result, str):
        return erreur("profil_invalide", result, 400)
    return jsonify(result)


@builder_bp.delete("/api/profiles/<name>")
def api_delete_profile(name: str):
    """supprimer un profil d'agent global ; 404 `profil_inconnu`"""
    if not profiles_svc.delete_profile(name):
        return erreur("profil_inconnu", f"profil inconnu : {name}", 404)
    return jsonify({"ok": True})


@builder_bp.get("/api/skills")
def api_list_skills():
    """toutes les skills découvertes, toutes sources → {skills:[{name, description, source,
    editable}]} — `editable` vaut true pour les skills globales (~/.bouzecode/skills), seules
    modifiables par cette API"""
    return jsonify({"skills": skills_svc.list_skills()})


@builder_bp.get("/api/skills/<path:name>")
def api_get_skill(name: str):
    """contenu markdown brut d'une skill → {name, content, source, editable}. `?new=1` renvoie un
    gabarit de nouvelle skill au lieu d'un contenu existant. 404 `skill_inconnue`."""
    if request.args.get("new"):
        return jsonify(skills_svc.new_skill_template(name))
    skill = skills_svc.get_skill(name)
    if skill is None:
        return erreur("skill_inconnue", f"skill inconnue : {name}", 404)
    return jsonify(skill)


@builder_bp.post("/api/skills")
def api_save_skill():
    """{name, content, create?} — créer/écraser une skill globale (~/.bouzecode/skills/<name>.md)
    → {name, path} ; `name` en minuscules/chiffres/-/_ et `content` non vide, sinon 400
    `skill_invalide` ; `create:true` → 409 `exists` si le nom est pris."""
    payload = json_body(request)
    try:
        result = skills_svc.save_skill(payload.get("name", ""), payload.get("content", ""),
                                       create=bool(payload.get("create")))
    except skills_svc.SkillExists as exc:
        return erreur("exists", str(exc), 409)
    if isinstance(result, str):
        return erreur("skill_invalide", result, 400)
    return jsonify(result)


@builder_bp.delete("/api/skills/<name>")
def api_delete_skill(name: str):
    """supprimer une skill globale (~/.bouzecode/skills/<name>.md) ; 404 `skill_inconnue` si ce
    n'est pas une skill globale — les skills builtin/projet ne sont pas supprimables ici"""
    if not skills_svc.delete_skill(name):
        return erreur("skill_inconnue", f"skill globale inconnue : {name}", 404)
    return jsonify({"ok": True})
