# [desc] Outils des routes de sessions : session ou 404 (forme unique), session décodée ou 404, réponse JSON lisible ou texte brut selon `?json`. [/desc]
from __future__ import annotations

from flask import make_response, request

from ...services.erreurs import Refus
from ...services.sessions import store


def session_ou_404(key: str):
    """La référence de la session, ou 404 `session_inconnue`."""
    ref = store.resolve(key)
    if ref is None:
        raise Refus("session_inconnue", f"session inconnue : {key}", 404, key=key)
    return ref


def donnees_ou_404(ref) -> dict:
    """Le JSON de la session, ou 404 `session_illisible` (pas encore écrite, ou illisible)."""
    data = store.load_session_json(ref.path)
    if data is None:
        raise Refus("session_illisible", "session pas encore écrite ou illisible", 404)
    return data


def json_ou_texte(resultat, en_texte):
    """`?json=1` → JSON indenté ; sinon le texte brut `en_texte(resultat)`."""
    from ...services.sessions.formatter import pretty_json
    if request.args.get("json"):
        reponse = make_response(pretty_json(resultat))
        reponse.content_type = "application/json"
        return reponse
    reponse = make_response(en_texte(resultat))
    reponse.content_type = "text/plain; charset=utf-8"
    return reponse
