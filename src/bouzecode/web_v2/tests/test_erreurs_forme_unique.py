# [desc] Garde GLOBALE (spec ticketing §9, critère 10) : toute réponse >= 400 d'une route /api/ a la forme unique {"error": {"code", "message"}} — chaque route du schéma est appelée avec des paramètres inconnus et un corps vide. [/desc]
"""On parcourt TOUTES les routes /api/ enregistrées (le schéma dérivé), chemin rempli avec des
identifiants qui n'existent pas, corps `{}` pour les mutations : ce qui échoue doit échouer à la
forme unique. Le HOME est jetable (plugin `pytest_home_etanche`) : rien de réel n'est touché.

Sont exclues les routes dont l'APPEL a un effet hors du HOME (redémarrer le serveur, installer
un paquet, joindre le réseau, écrire un fichier au chemin figé à l'import) : elles sont couvertes par leurs propres tests."""
from __future__ import annotations

import re

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.schema import routes_api

HORS_HOME = {
    "POST /api/server/restart", "POST /api/server/shutdown", "POST /api/plugins",
    "POST /api/plugins/from-gitlab", "POST /api/agents/install", "POST /api/agents/catalog/refresh",
    "POST /api/agents/<name>/upgrade-plugins", "POST /api/agents/import",
    "POST /api/env-sanity/recheck", "GET /api/agents/catalog",
    #  Réussit avec un corps vide et écrit un fichier dont le chemin est figé à l'import.
    "PUT /api/bureau/assistant/contexte",
}


@pytest.fixture()
def app():
    return create_app()


def _cles(application):
    return sorted({cle for cle, _vue in routes_api(application)} - HORS_HOME)


def _url(cle: str) -> tuple[str, str]:
    methode, regle = cle.split(" ", 1)
    return methode, re.sub(r"<(?:int:)?([a-z_]+)>",
                           lambda m: "0" if m.group(1) in ("n", "i", "turn") else "inconnu000x",
                           regle)


def test_toute_erreur_d_une_route_api_a_la_forme_unique(app):
    client, fautes = app.test_client(), []
    for cle in _cles(app):
        methode, url = _url(cle)
        reponse = client.open(url, method=methode,
                              json={} if methode in ("POST", "PUT", "PATCH") else None)
        if reponse.status_code < 400:
            continue
        corps = reponse.get_json(silent=True)
        erreur = corps.get("error") if isinstance(corps, dict) else None
        if not (isinstance(erreur, dict) and erreur.get("code") and erreur.get("message")):
            fautes.append(f"{cle} → {reponse.status_code} {reponse.get_data(as_text=True)[:120]!r}")
    assert fautes == [], "réponses d'erreur hors de la forme unique :\n" + "\n".join(fautes)


@pytest.mark.parametrize("methode, url", [("GET", "/api/route-qui-n-existe-pas"),
                                          ("DELETE", "/api/schema")])
def test_une_erreur_du_protocole_sous_api_a_aussi_la_forme_unique(app, methode, url):
    reponse = app.test_client().open(url, method=methode)
    assert reponse.status_code in (404, 405)
    assert reponse.get_json()["error"]["code"] in ("not_found", "method_not_allowed")


def test_aucun_service_n_importe_une_route():
    """Inversion de couches interdite : un service lève `services.erreurs.Refus`, la ROUTE le
    sérialise. Un service qui importerait `routes/_errors` dépendrait de Flask et des routes."""
    from pathlib import Path
    services = Path(__file__).resolve().parents[1] / "services"
    import_de_route = re.compile(r"^\s*(?:from|import)\s+(?:\.+routes|bouzecode\.web_v2\.routes)",
                                 re.MULTILINE)
    fautifs = [str(f.relative_to(services)) for f in services.rglob("*.py")
               if "tests" not in f.parts and import_de_route.search(f.read_text(encoding="utf-8"))]
    assert fautifs == []
