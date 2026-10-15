# [desc] Garde des mutations /api/ : jeton local X-Bouzecode-Token (401) et corps JSON obligatoire (415). Spec ticketing B8 / S1. [/desc]
"""Deux gardes posées sur toute requête, avant le handler (spec ticketing B8, constat S1).

1. **Jeton** : tout POST/PUT/PATCH/DELETE sous `/api/` exige l'en-tête `X-Bouzecode-Token`
   égal au jeton du parc (`backend.core.jeton_local`), sinon 401 `jeton_manquant` /
   `jeton_invalide`. Un onglet tiers ne peut pas le lire : il ne peut plus lancer, tuer ni
   merger par un POST cross-origin.
2. **Type de contenu** : un POST/PUT/PATCH à corps NON VIDE doit être `application/json`,
   sinon 415 `type_contenu_invalide`. C'est ce qui ferme la porte du `text/plain` envoyé sans
   préflight. Un corps vide reste accepté (beaucoup de gestes n'ont pas de paramètre).

Le jeton est lu une fois, à la création de l'app (`app.config["BOUZECODE_TOKEN"]`), et servi
aux pages par une balise meta que lit `static/js/lib/ui.js`.
"""
from __future__ import annotations

import hmac

from flask import Flask, current_app, request

from ..backend.core.jeton_local import EN_TETE, assurer_jeton
from .routes._errors import erreur

METHODES_MUTANTES = frozenset({"POST", "PUT", "PATCH", "DELETE"})
METHODES_A_CORPS = frozenset({"POST", "PUT", "PATCH"})
HOTES_LOCAUX = frozenset({"127.0.0.1", "localhost", "::1"})


def _refus_jeton():
    attendu = current_app.config.get("BOUZECODE_TOKEN") or ""
    recu = request.headers.get(EN_TETE, "")
    if not recu:
        return erreur("jeton_manquant", f"En-tête {EN_TETE} absent : toute modification exige "
                      "le jeton local (~/.bouzecode/web_v2/token).", 401)
    if not attendu or not hmac.compare_digest(recu, attendu):
        return erreur("jeton_invalide", f"En-tête {EN_TETE} invalide : relis le jeton dans "
                      "~/.bouzecode/web_v2/token (ou recharge la page).", 401)
    return None


def _refus_type_de_contenu():
    if request.method not in METHODES_A_CORPS or not request.content_length:
        return None
    if request.mimetype == "application/json":
        return None
    return erreur("type_contenu_invalide",
                  f"Corps attendu en application/json (reçu : {request.mimetype or 'aucun type'}).",
                  415, recu=request.mimetype or "")


def garder_les_mutations():
    if request.method not in METHODES_MUTANTES or not request.path.startswith("/api/"):
        return None
    return _refus_jeton() or _refus_type_de_contenu()


def installer(app: Flask) -> None:
    app.config["BOUZECODE_TOKEN"] = assurer_jeton()
    app.before_request(garder_les_mutations)

    @app.context_processor
    def jeton_des_pages():
        """Le jeton, lu par `ui.js` dans `<meta name="bouzecode-token">` (base.html)."""
        return {"bouzecode_token": app.config["BOUZECODE_TOKEN"]}


def avertir_si_hote_expose(hote: str) -> str:
    """Message d'avertissement si le serveur écoute hors de la boucle locale ("" sinon).

    Le jeton est toujours actif, donc on n'interdit pas ; on prévient : toute machine qui
    joint ce port peut LIRE l'API (les GET ne sont pas protégés)."""
    if hote in HOTES_LOCAUX:
        return ""
    return (f"web_v2: ATTENTION, écoute sur {hote} (hors boucle locale). Les mutations "
            f"exigent le jeton {EN_TETE}, mais toutes les lectures /api/ sont exposées au réseau.")
