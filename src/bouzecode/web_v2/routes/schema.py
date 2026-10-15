# [desc] GET /api/schema (le schéma DÉRIVÉ des routes enregistrées) et GET /api/lexique (le lexique unique de l'écran). [/desc]
from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from ..schema import build_api_schema

schema_bp = Blueprint("schema_api", __name__)


@schema_bp.get("/api/schema")
def api_schema():
    """ce schéma : toutes les routes /api/ du serveur, dérivées de app.url_map → {description,
    endpoints: {"MÉTHODE /chemin": description (1er paragraphe du docstring de la vue)}, corps:
    {"MÉTHODE /chemin": {champ: contrainte}} (corps déclarés par `@corps_attendu`)}"""
    return jsonify(build_api_schema(current_app))


@schema_bp.get("/api/lexique")
def api_lexique():
    """le lexique UNIQUE de l'écran (services/work/lexique.py) : {entrees: {clé: {mot, aide, ton,
    icone}}, motifs: {motif d'attente: clé}, tickets: {statut de ticket: clé}} — les mêmes mots
    pour les tâches du Bureau, les agents, les motifs « À traiter » et les tickets
    (`status_ui`). Aussi injecté dans chaque page (`<script id="bz-lexique">`)."""
    from ..services.work import lexique
    return jsonify(lexique.table())
