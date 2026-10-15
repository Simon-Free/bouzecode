# [desc] Lot L6 — les routes dépréciées et les pages /projects, /files sont RETIRÉES : aucune n'est enregistrée (404), et aucune n'apparaît plus dans le code (front, backend, skills, profils, outils du bac à sable). [/desc]
"""Garde statique : un appelant oublié d'une route retirée ne tomberait en panne qu'à l'usage
(404). On cherche donc les chemins retirés dans tout ce qui APPELLE le serveur : le code de
`src/bouzecode` (hors tests et `static/vendor`), les skills, les profils intégrés, `scripts/` et
les outils du bac à sable. Les tests, eux, peuvent nommer une route retirée pour prouver son 404.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from bouzecode.web_v2.schema.application import application_des_routes

RACINE = Path(__file__).resolve().parents[4]
SEG = r"[^/\s\"'`]+"
RETIREES = [
    r"/api/dispatch\b", r"/api/tickets/", r"/api/agent/message\b",
    rf"/api/agents/{SEG}/(?:continue|kill|enfants)\b", rf"/api/agents/{SEG}/interrupt\b(?!ions)",
    rf"/api/conversations/{SEG}/relaunch\b", r"/api/agents/launch\b", r"/api/agents/awaiting\b",
    r"/api/agents/unreachable\b", r"/api/conversations/interrupted\b", r"/api/interrupted\b",
    rf"/api/projects/{SEG}/agents\b", r"/api/files\b",
]
MOTIF = re.compile("|".join(RETIREES))
SOURCES = [RACINE / "src" / "bouzecode", RACINE / ".bouzecode" / "skills", RACINE / "scripts",
           RACINE / "tests" / "sandbox"]
EXTENSIONS = {".py", ".js", ".html", ".md", ".yaml", ".yml", ".ps1", ".sh", ".txt"}


def _fichiers_appelants():
    for racine in SOURCES:
        for chemin in racine.rglob("*"):
            parties = set(chemin.relative_to(racine).parts)
            if (chemin.suffix in EXTENSIONS and chemin.is_file()
                    and not parties & {"tests", "vendor", "__pycache__", "node_modules"}):
                yield chemin


def test_aucun_appelant_ne_nomme_une_route_retiree():
    fautes = []
    for chemin in _fichiers_appelants():
        texte = chemin.read_text(encoding="utf-8", errors="replace")
        for trouve in MOTIF.finditer(texte):
            ligne = texte.count("\n", 0, trouve.start()) + 1
            fautes.append(f"{chemin.relative_to(RACINE)}:{ligne} {trouve.group(0)}")
    assert fautes == [], "routes retirées (L6) encore nommées :\n" + "\n".join(fautes)


def test_aucune_route_retiree_n_est_enregistree():
    regles = [regle.rule for regle in application_des_routes().url_map.iter_rules()]
    exemples = [re.sub(r"<[^>]+>", "x", r) for r in regles]
    assert [r for r in exemples if MOTIF.search(r)] == []


@pytest.mark.parametrize("methode, chemin", [
    ("POST", "/api/dispatch"), ("GET", "/api/tickets/p/t1"), ("POST", "/api/tickets/p/t1/done"),
    ("POST", "/api/agents/a1/continue"), ("GET", "/api/agents/a1/enfants"),
    ("GET", "/api/interrupted"), ("GET", "/projects"), ("GET", "/files"),
    ("GET", "/api/files/tree"),
])
def test_une_route_ou_une_page_retiree_repond_404(methode, chemin):
    from bouzecode.web_v2.app import create_app
    reponse = create_app().test_client().open(chemin, method=methode, json={})
    assert reponse.status_code in (404, 405), (chemin, reponse.status_code)
