# [desc] API projets: ouvrir/lister/fermer, agents par projet, liste des modèles du registry. [/desc]
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ...schema import corps_attendu
from .._body import json_body
from .._errors import erreur
from ....backend.agent.providers.registry import PROVIDERS
from ...services.work import dismissed_paths, projects

projects_bp = Blueprint("projects_api", __name__)


@projects_bp.get("/api/projects/dismissed")
def api_dismissed_list():
    """Les dossiers dont l'utilisateur a dit qu'ils ne sont pas des projets.

    Exposé pour être ANNULABLE depuis l'interface : un « non » donné trop vite
    serait sinon définitif et invisible.
    """
    return jsonify({"dismissed": dismissed_paths.list_dismissed()})


@projects_bp.post("/api/projects/dismissed")
def api_dismissed_add():
    """{path, reason?} — enregistrer qu'un dossier n'est PAS un projet, pour que la
    question ne soit plus jamais posée dessus. Idempotent."""
    payload = json_body(request)
    path = (payload.get("path") or "").strip()
    if not path:
        return erreur("champ_requis", "path requis", 400, champs=["path"])
    return jsonify(dismissed_paths.dismiss(path, reason=(payload.get("reason") or "").strip()))


@projects_bp.delete("/api/projects/dismissed")
def api_dismissed_remove():
    """{path} — annuler un écart : le dossier redevient inconnu et la question
    pourra être posée de nouveau. 404 si le chemin n'était pas écarté."""
    payload = json_body(request)
    path = (payload.get("path") or "").strip()
    if not path:
        return erreur("champ_requis", "path requis", 400, champs=["path"])
    if not dismissed_paths.undismiss(path):
        return erreur("chemin_non_ecarte", f"chemin non écarté : {path}", 404, path=path)
    return jsonify({"undismissed": path})


@projects_bp.get("/api/projects")
def api_projects_overview():
    """projets ouverts (un par path/worktree) + compteurs (agents en cours/en attente, tickets à
    relire)"""
    return jsonify({"projects": projects.overview()})


@projects_bp.post("/api/projects")
@corps_attendu(name="texte, requis", path="dossier existant, requis",
               description="texte ≤ 200 car.")
def api_projects_add():
    """{name, path, description?} — ouvrir un projet (description optionnelle, <=200 car.) → 201
    {project}. 400 `champ_requis` / `chemin_invalide`."""
    payload = json_body(request)
    name = (payload.get("name") or "").strip()
    path = (payload.get("path") or "").strip()
    description = (payload.get("description") or "").strip()
    if not name or not path:
        return erreur("champ_requis", "name et path requis", 400,
                      champs=[nom for nom, val in (("name", name), ("path", path)) if not val])
    result = projects.add_project(name, path, description)
    if isinstance(result, str):
        return erreur("chemin_invalide", result, 400)
    return jsonify(result), 201


@projects_bp.patch("/api/projects/<slug>")
@corps_attendu(description="texte ≤ 200 car.")
def api_projects_update(slug: str):
    """{description} — éditer la description d'un projet (persistée dans projects.json)"""
    payload = json_body(request)
    description = (payload.get("description") or "").strip()
    result = projects.update_project(slug, description)
    if result is None:
        return erreur("projet_inconnu", f"projet inconnu : {slug}", 404, slug=slug)
    return jsonify(result)


@projects_bp.delete("/api/projects/<slug>")
def api_projects_remove(slug: str):
    """retirer un projet de la liste des projets ouverts (projects.json); n'efface rien sur le
    disque. 404 si slug inconnu."""
    if not projects.remove_project(slug):
        return erreur("projet_inconnu", f"projet inconnu : {slug}", 404, slug=slug)
    return jsonify({"ok": True})


@projects_bp.get("/api/projects/<slug>/fichiers-non-suivis")
def api_projet_fichiers_non_suivis(slug: str):
    """?indices=mots séparés par des espaces → {ok, slug, chemin, git {branche, head, amont,
    commits, modifications_non_commitees}, non_suivis [{chemin, taille, pertinent, exclu?,
    indices?}], non_suivis_total, tronque, proposes, secrets_signales} : les fichiers NON SUIVIS
    à transmettre à un agent lancé (même service que l'outil `Projets(action="fichiers")`).
    Les secrets sont signalés, jamais proposés. LECTURE PURE (git status/ls-files). 404
    `projet_inconnu`, 409 `pas_un_depot_git`."""
    from ...services.work import projets_etat
    resultat = projets_etat.fichiers(slug, (request.args.get("indices") or "").split())
    if resultat.get("ok"):
        return jsonify(resultat)
    if resultat.get("erreur") == "projet_inconnu":
        return erreur("projet_inconnu", f"projet inconnu : {slug}", 404, slug=slug)
    return erreur(str(resultat.get("erreur")), f"{slug} n'est pas un dépôt git", 409,
                  chemin=resultat.get("chemin"))


@projects_bp.get("/api/models")
def api_models():
    """modèles disponibles (menu déroulant) : {name, provider} par modèle du registry"""
    models = [
        {"name": model, "provider": provider_name}
        for provider_name, provider in PROVIDERS.items()
        for model in provider["models"]
    ]
    return jsonify({"models": models, "default": ""})
