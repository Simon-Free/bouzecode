# [desc] La page Agent builder sert un parcours en 3 etapes et ses scripts ne reclament aucun id absent. [/desc]
"""Agent builder : la page de creation, vue depuis le navigateur du proprietaire.

Niveau 3 (client de test Flask) : on lit le HTML servi. Pas de navigateur — rien
ici ne demande d'executer du JavaScript. Le piege de cette page est ailleurs :
ses scripts pilotent le DOM par `getElementById`, si bien qu'un id renomme dans
le template casse la page sans qu'aucune reponse HTTP ne bronche. Le dernier test
relit donc les scripts reellement references par la page et exige que chaque id
qu'ils reclament existe dans le HTML.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from bouzecode.web_v2.app import create_app

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@pytest.fixture()
def page_html() -> str:
    """Le HTML de /agent-builder tel que le navigateur le recoit."""
    client = create_app().test_client()
    response = client.get("/agent-builder")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_la_creation_se_lit_en_trois_etapes_numerotees(page_html):
    """La colonne de creation annonce Identity, Capabilities puis Prompt, dans cet ordre.

    Depuis la bilinguisation, l'etiquette de l'etape vit dans son propre <span data-i18n>
    (sinon `applyDom` ecraserait la pastille numerotee en reecrivant le titre entier). Le
    HTML servi est en ANGLAIS : c'est la langue par defaut, celle qui evite le scintillement.
    """
    etapes = re.findall(
        r'ab-num">(\d)</span>\s*<span data-i18n="[^"]+">([A-Za-zÀ-ÿ]+)</span>', page_html
    )
    assert etapes == [("1", "Identity"), ("2", "Capabilities"), ("3", "Prompt")]


def test_les_capacites_sont_repliees_derriere_un_resume(page_html):
    """Les listes de cases a cocher n'accueillent pas le lecteur : elles sont dans un
    <details> ferme, resume par un compteur tools/skills."""
    capacites = re.search(r'<details class="ab-step" id="b-caps">', page_html)
    assert capacites, "l'etape Capacites doit etre un <details> replie"
    assert "open" not in page_html[capacites.start():capacites.end()]
    assert 'id="b-caps-recap"' in page_html


def test_le_catalogue_les_plugins_et_les_skills_sont_dans_des_onglets(page_html):
    """Catalogue, plugins et editeur de skills ne s'intercalent plus dans le parcours :
    ils vivent dans des panneaux masques, atteignables par les onglets."""
    for panel in ("ab-panel-catalog", "ab-panel-plugins", "ab-panel-skills"):
        assert f'data-panel="{panel}"' in page_html, f"onglet manquant pour {panel}"
        assert re.search(rf'id="{panel}" hidden', page_html), f"{panel} devrait etre masque"
    assert re.search(r'id="ab-panel-build"(?! hidden)', page_html)


def test_le_prompt_complet_calcule_reste_atteignable_replie(page_html):
    """Le prompt complet calcule — ce que l'agent a vraiment en tete — est present,
    replie sous la zone d'edition."""
    assert 'id="b-preview"' in page_html
    assert re.search(r'id="b-preview-out" hidden', page_html)
    assert 'id="b-preview-prompt"' in page_html


def _ids_reclames_par(script: Path) -> set[str]:
    code = script.read_text(encoding="utf-8")
    return (
        set(re.findall(r'getElementById\("([^"]+)"\)', code))
        | set(re.findall(r'(?<![\w.])[$g]\("([^"]+)"\)', code))
        | set(re.findall(r'querySelector(?:All)?\("#([\w-]+)', code))
    )


def test_chaque_id_pilote_par_les_scripts_existe_dans_la_page(page_html):
    """Aucun script de la page ne reclame un id que le template ne rend pas."""
    scripts = re.findall(r'<script src="/static/(js/[\w.\-]+\.js)"', page_html)
    assert scripts, "la page doit charger ses scripts"
    presents = set(re.findall(r'id="([^"]+)"', page_html))

    absents = {}
    for nom in scripts:
        fichier = STATIC_DIR / nom
        assert fichier.is_file(), f"script reference mais absent du disque : {nom}"
        manquants = sorted(_ids_reclames_par(fichier) - presents)
        if manquants:
            absents[nom] = manquants
    assert absents == {}
