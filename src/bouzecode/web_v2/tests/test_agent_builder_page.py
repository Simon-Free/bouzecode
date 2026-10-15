# [desc] La page Profils sert un maître/détail (liste, éditeur, aperçu en direct, tiroirs fermés) et ses modules ne réclament aucun id absent. [/desc]
"""Profils (/agent-builder) : la page telle que le navigateur la reçoit (SPEC §6).

Niveau 3 (client de test Flask) : on lit le HTML servi, sans navigateur. Le piège de cette
page : ses modules pilotent le DOM par `getElementById` / `$("…")`, si bien qu'un id renommé
dans le gabarit casse la page sans qu'aucune réponse HTTP ne bronche. Le dernier test relit
donc TOUS les modules de static/js/profils/ et exige que chaque id réclamé existe dans le HTML.
Le comportement (clics, aperçu, toasts) est prouvé en navigateur dans
`tests/e2e_sandbox/test_profils_e2e.py`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from bouzecode.web_v2.app import create_app

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@pytest.fixture()
def page_html() -> str:
    client = create_app().test_client()
    response = client.get("/agent-builder")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_le_titre_de_l_onglet_dit_profils(page_html):
    assert re.search(r"<title>\s*Profils", page_html)


def test_maitre_detail_liste_editeur_et_apercu(page_html):
    """Une liste des profils, un éditeur, et l'aperçu du prompt calculé TOUJOURS visible
    (plus caché derrière un lien, plus périmé)."""
    for ident in ("pf-list", "pf-new", "pf-form", "pf-save", "pf-preview-body", "pf-preview-state"):
        assert f'id="{ident}"' in page_html, ident
    assert not re.search(r'id="pf-preview-body"[^>]*hidden', page_html)


def test_enregistrer_est_desactive_tant_que_rien_n_a_change(page_html):
    assert re.search(r'id="pf-save"[^>]*disabled', page_html)


def test_catalogue_et_bibliotheque_sont_des_tiroirs_fermes(page_html):
    """La plomberie (catalogue, skills, plugins) ne concurrence plus la tâche principale."""
    for drawer in ("pf-catalog", "pf-library"):
        m = re.search(rf'<aside id="{drawer}"[^>]*>', page_html)
        assert m, drawer
        assert 'data-open="false"' in m.group(0) and 'aria-hidden="true"' in m.group(0)


def test_plus_aucun_ancien_script_du_builder(page_html):
    assert "js/agent_builder" not in page_html
    assert 'src="/static/js/profils/main.js"' in page_html


def _ids_reclames(code: str) -> set[str]:
    return (
        set(re.findall(r'getElementById\("([^"]+)"\)', code))
        | set(re.findall(r'(?<![\w.])\$\("([^"$]+)"\)', code))
        | set(re.findall(r'querySelector(?:All)?\("#([\w-]+)', code))
    )


def test_chaque_id_pilote_par_les_modules_existe_dans_la_page(page_html):
    """Aucun module de static/js/profils/ ne réclame un id que le gabarit ne rend pas
    (les ids fabriqués dynamiquement — pf-hook-*, pf-sugg-* — sont exclus)."""
    presents = set(re.findall(r'id="([^"]+)"', page_html))
    absents = {}
    for fichier in sorted((STATIC_DIR / "js" / "profils").glob("*.js")):
        manquants = sorted(i for i in _ids_reclames(fichier.read_text(encoding="utf-8")) - presents
                           if not i.startswith(("pf-hook-", "pf-sugg-")))
        if manquants:
            absents[fichier.name] = manquants
    assert absents == {}
