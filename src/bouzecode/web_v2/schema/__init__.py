# [desc] Schéma d'API DÉRIVÉ des routes enregistrées : clés « MÉTHODE /chemin », docstrings des vues, corps déclarés par `@corps_attendu`. Rien n'est saisi à la main. [/desc]
"""`GET /api/schema` et la skill `web-api.md` sortent de ce module (spec ticketing §6.5, P7).

* la liste des routes vient de `app.url_map` : une route ajoutée apparaît, une route retirée
  disparaît, sans table à tenir à jour ;
* la description d'une route est le PREMIER PARAGRAPHE du docstring de sa vue ;
* le corps attendu d'une mutation est déclaré à côté de la route par `@corps_attendu(...)`.
"""
from __future__ import annotations

import inspect
import re

SCHEMA_DESCRIPTION = (
    "bouzeui v2 — API JSON consommable par un LLM. Lecture : GET ; actions : POST/PUT/PATCH/"
    "DELETE (en-tête X-Bouzecode-Token, corps application/json). Erreurs : code HTTP >= 400 et "
    "{error: {code, message, details?}}. Schéma DÉRIVÉ de app.url_map : il liste exactement les "
    "routes /api/ enregistrées ; `corps` donne le corps attendu des mutations qui le déclarent."
)

_CONVERTER_PREFIX = re.compile(r"<[^:>]+:([^>]+)>")
_NON_API_METHODS = frozenset({"HEAD", "OPTIONS"})
_ATTRIBUT_CORPS = "__corps_attendu__"


def schema_key(rule: str, method: str) -> str:
    """Clé canonique d'un endpoint : « POST /api/projects/<slug>/tickets/<ticket_id>/runs »."""
    canonical_rule = _CONVERTER_PREFIX.sub(r"<\1>", rule)
    return f"{method} {canonical_rule}"


def docstring_summary(view) -> str:
    """Premier paragraphe du docstring d'une vue, replié sur une ligne ('' si absent)."""
    doc = inspect.getdoc(view) or ""
    return " ".join(doc.split("\n\n", 1)[0].split())


def corps_attendu(**champs: str):
    """Déclare le corps JSON d'une mutation, À CÔTÉ de sa route (sous le décorateur de route) :

        @bp.post("/api/projects/<slug>/tickets")
        @corps_attendu(title="texte ≤ 200 car., requis", prompt="texte, requis")
        def api_tickets_creer(slug): ...

    Chaque valeur est une phrase courte : type, contrainte, défaut. La vue n'est pas enveloppée."""
    def poser(vue):
        setattr(vue, _ATTRIBUT_CORPS, dict(champs))
        return vue
    return poser


def corps_de(view) -> dict | None:
    return getattr(view, _ATTRIBUT_CORPS, None) or getattr(inspect.unwrap(view), _ATTRIBUT_CORPS, None)


def routes_api(app):
    """(clé, vue) de chaque couple (méthode, règle) /api/ réellement enregistré."""
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/"):
            continue
        view = app.view_functions[rule.endpoint]
        for method in sorted(rule.methods - _NON_API_METHODS):
            yield schema_key(rule.rule, method), view


def build_api_schema(app) -> dict:
    """{description, endpoints: {clé: description}, corps: {clé: {champ: contrainte}}}."""
    endpoints, corps = {}, {}
    for key, view in routes_api(app):
        endpoints[key] = docstring_summary(view)
        declare = corps_de(view)
        if declare:
            corps[key] = declare
    return {"description": SCHEMA_DESCRIPTION, "endpoints": dict(sorted(endpoints.items())),
            "corps": dict(sorted(corps.items()))}
