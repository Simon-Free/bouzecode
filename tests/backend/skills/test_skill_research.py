# [desc] SkillResearch vu de l'agent : recherche par mots-clés sur de vrais dossiers de skills. [/desc]
"""SkillResearch sur un vrai `.bouzecode/skills` temporaire, via le registre d'outils.

Les skills globales de la machine restent visibles : les mots-clés des tests sont
choisis pour n'appartenir qu'aux skills écrites ici.
"""
from __future__ import annotations

import pytest

import bouzecode.backend.core.paths as _paths
import bouzecode.backend.tools.registration  # noqa: F401 — enregistre les outils
from bouzecode.backend.core.tool_registry import execute_tool, get_tool, is_enabled
from bouzecode.backend.tools.skill.research import skill_research
from bouzecode.backend.tools.skill.tools import _skill_tool

SKILLS = {
    "zebra-deploy": ("Deploy the stack.", "# Steps\nRun it.\n"),
    "quokka-cache": ("ALWAYS LOAD WHEN tuning the quokka cache. Use cases: (1) eviction, (2) TTL",
                     "# Cache\nNothing about stripes.\n"),
    "stripes-doc": ("Explains zebra stripes for the docs.", "# Doc\n"),
    "burrow": ("Underground storage.", "# Intro\ntext\n## Rollback du wombat\nétapes\n"),
    "rongeur": ("Déployer le capybara en production.", "# Corps\n"),
}


@pytest.fixture(autouse=True)
def projet(tmp_path, monkeypatch):
    """Un projet équipé de cinq skills, branché comme au démarrage dans son dossier."""
    for name, (description, body) in SKILLS.items():
        folder = tmp_path / ".bouzecode" / "skills" / name
        folder.mkdir(parents=True)
        (folder / "skill.md").write_text(
            f'---\nname: {name}\ndescription: "{description}"\n---\n\n{body}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    _paths.register_extra_dirs([str(tmp_path / ".bouzecode")])
    yield tmp_path
    _paths._extra_dirs = []


def research(query: str, config: dict | None = None, **params) -> str:
    return execute_tool("SkillResearch", {"query": query, **params}, config or {})


def test_l_outil_est_toujours_disponible():
    assert get_tool("SkillResearch") is not None and is_enabled("SkillResearch")
    assert get_tool("SkillList") is None


def test_le_nom_passe_avant_la_description():
    sortie = research("zebra")
    assert sortie.index("- zebra-deploy") < sortie.index("- stripes-doc")


def test_une_ligne_par_skill_sans_le_boilerplate():
    sortie = research("quokka")
    assert "- quokka-cache — Tuning the quokka cache" in sortie
    assert "ALWAYS LOAD" not in sortie
    assert "Use cases" not in sortie


def test_un_match_dans_le_corps_montre_la_ligne():
    sortie = research("wombat")
    assert "- burrow — Underground storage." in sortie
    assert "↳ corps L3: ## Rollback du wombat" in sortie


def test_insensible_aux_accents_et_a_la_casse():
    assert "- rongeur — " in research("DEPLOYER capybara")
    assert "- rongeur — " in research("déployé")


def test_plusieurs_mots_cles_classent_par_nombre_de_mots_trouves():
    sortie = research("stripes docs zebra")
    assert sortie.index("- stripes-doc") < sortie.index("- zebra-deploy")


def test_limit_borne_le_nombre_de_resultats():
    sortie = research("zebra quokka wombat capybara", limit=2)
    assert "(2 sur " in sortie
    assert sum(line.startswith("- ") for line in sortie.splitlines()) == 2


def test_la_sortie_dit_comment_ouvrir():
    assert research("zebra").splitlines()[-1] == 'Ouvrir : Skill(name="<nom>")'


def test_le_profil_filtre_les_skills():
    sortie = research("zebra", {"_profile_skills": ["stripes-doc"]})
    assert "- stripes-doc" in sortie
    assert "zebra-deploy" not in sortie


def test_aucun_resultat_le_dit_et_suggere_d_autres_termes():
    sortie = research("ornithorynque")
    assert "Aucune skill ne correspond à « ornithorynque »" in sortie
    assert "Essaie d'autres mots-clés" in sortie


def test_query_vide_refusee():
    assert skill_research({"query": "   "}, {}).startswith("Erreur : query vide")


def test_skill_introuvable_propose_les_resultats_de_la_recherche():
    sortie = _skill_tool({"name": "quokka-tuning"}, {})
    assert "not found" in sortie
    assert "- quokka-cache — " in sortie
