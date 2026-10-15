# [desc] Tests de LoadProjectConfig : trois états, projets enfants, silences, briefing snippetable. [/desc]
"""LoadProjectConfig vu de l'agent.

Le scénario qui a motivé ces tests : un agent lancé dans `demo/` — un dossier
qui n'est pas un projet mais qui en contient trois — repartait les mains vides,
sans skill ni carte, et sans savoir quoi faire à la place.
"""
import json
import os
from pathlib import Path

import pytest

from bouzecode.backend.core import paths
from bouzecode.backend.tools.ops.project_config import _load_project_config
from bouzecode.web_v2.services.work import dismissed_paths, projects, worktrees


@pytest.fixture()
def monde(tmp_path, monkeypatch):
    """Un conteneur `demo/` avec deux projets dedans, dont un équipé."""
    monkeypatch.setattr(projects, "PROJECTS_PATH", tmp_path / "projects.json")
    monkeypatch.setattr(dismissed_paths, "DISMISSED_PATH", tmp_path / "dismissed.json")
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "worktrees")
    monkeypatch.setattr(paths, "_extra_dirs", [], raising=False)

    conteneur = tmp_path / "demo"
    equipe = conteneur / "demo_application"
    nu = conteneur / "demo_ingestion"
    for dossier in (equipe, nu):
        dossier.mkdir(parents=True)

    skills = equipe / ".bouzecode" / "skills" / "conversation-download"
    skills.mkdir(parents=True)
    (skills / "skill.md").write_text(
        '---\nname: conversation-download\n'
        'description: "ALWAYS LOAD WHEN you need the CONTENT of a Focus conversation."\n'
        "---\n\n# Corps\n",
        encoding="utf-8",
    )
    plugin = equipe / ".bouzecode" / "plugins" / "conversation-download"
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text(
        json.dumps({"name": "conversation-download",
                    "description": "Download a Focus conversation from PostgreSQL.",
                    "tools": ["module_test_dl"]}),
        encoding="utf-8",
    )
    (plugin / "module_test_dl.py").write_text(
        'TOOLS = [{\n'
        '    "name": "DownloadTest",\n'
        '    "description": "Download a Focus conversation from PostgreSQL.",\n'
        '    "input_schema": {"type": "object", "properties": {}, "required": []},\n'
        '    "func": lambda params, config: "ok",\n'
        '    "read_only": True,\n'
        "}]\n",
        encoding="utf-8",
    )
    (equipe / "AGENTS.md").write_text("# carte\n", encoding="utf-8")

    projects.add_project("demo_application", str(equipe))
    projects.add_project("demo_ingestion", str(nu))
    return {"conteneur": conteneur, "equipe": equipe, "nu": nu, "tmp": tmp_path}


def test_projet_designe_compte_ses_skills_et_donne_l_acces_a_son_code(monde):
    sortie = _load_project_config(str(monde["equipe"]))

    assert "Projet : demo_application" in sortie
    assert "## Skills (1) — 1 skill de projet disponible" in sortie
    assert 'SkillResearch(query="<mots-clés>")' in sortie
    assert f'FindCode(query="<mots-clés ou noms>", path="{monde["equipe"]}")' in sortie
    assert f'Tree(path="{monde["equipe"]}")' in sortie


def test_le_briefing_ne_liste_plus_les_skills(monde):
    """Ni nom ni description : la recherche passe par SkillResearch, à la demande."""
    sortie = _load_project_config(str(monde["equipe"]))

    assert "conversation-download — " not in sortie
    assert "ALWAYS LOAD WHEN" not in sortie
    assert sortie.index("## Skills") < sortie.index("## Outils projet") < sortie.index("## Code")


def test_la_skill_du_projet_est_trouvee_par_skill_research_apres_chargement(monde, monkeypatch):
    from bouzecode.backend.tools.skill.research import skill_research

    monkeypatch.chdir(monde["equipe"])
    _load_project_config(str(monde["equipe"]))

    trouve = skill_research({"query": "focus conversation"}, {})
    assert "conversation-download — You need the CONTENT of a Focus conversation." in trouve


def test_le_briefing_rappelle_de_le_snippeter(monde):
    assert "Snippet ce résultat" in _load_project_config(str(monde["equipe"]))


def test_les_outils_du_projet_sont_branches_et_appelables(monde):
    """Le plugin ne doit pas être seulement décrit : son outil doit être
    enregistré ET allumé, sinon la liste blanche d'import le laisse invisible."""
    from bouzecode.backend.core.tool_registry import _registry, is_enabled

    sortie = _load_project_config(str(monde["equipe"]))

    assert "## Outils projet (1) — appelables dès maintenant" in sortie
    assert "- DownloadTest" in sortie
    assert "DownloadTest" in _registry
    assert is_enabled("DownloadTest")


def test_un_plugin_cassé_est_signalé_sans_priver_des_autres(monde):
    """Une dépendance manquante dans un plugin ne doit pas coûter tout le projet."""
    casse = monde["equipe"] / ".bouzecode" / "plugins" / "casse"
    casse.mkdir(parents=True)
    (casse / "plugin.json").write_text(
        json.dumps({"name": "casse", "tools": ["module_casse"]}), encoding="utf-8")
    (casse / "module_casse.py").write_text(
        "import une_dependance_absente\nTOOLS = []\n", encoding="utf-8")

    sortie = _load_project_config(str(monde["equipe"]))

    assert "[plugin non chargé] casse:" in sortie
    assert "- DownloadTest" in sortie, "le plugin sain doit rester branché"


def test_conteneur_inconnu_liste_ses_projets_et_fait_poser_la_question(monde):
    sortie = _load_project_config(str(monde["conteneur"]))

    assert "n'est pas enregistré comme projet" in sortie
    assert "Projets enregistrés à l'intérieur (2)" in sortie
    assert "demo_application" in sortie and "demo_ingestion" in sortie
    assert "AskUserQuestion" in sortie
    assert "DismissProject" in sortie
    assert "Ne réponds JAMAIS à sa place" in sortie


def test_le_conteneur_annonce_ce_que_chaque_enfant_apporte(monde):
    """De quoi choisir entre les enfants sans avoir à tous les ouvrir."""
    sortie = _load_project_config(str(monde["conteneur"]))

    assert "1 skill, 1 plugin" in sortie
    assert "rien d'équipé" in sortie


def test_conteneur_ecarte_ne_repose_plus_la_question(monde):
    dismissed_paths.dismiss(monde["conteneur"], reason="conteneur de depots")

    sortie = _load_project_config(str(monde["conteneur"]))

    assert "n'est pas un projet" in sortie
    assert "conteneur de depots" in sortie
    assert "Projets enregistrés à l'intérieur (2)" in sortie
    assert "AskUserQuestion" not in sortie


def test_un_worktree_est_equipe_mais_jamais_propose_a_l_enregistrement(monde, monkeypatch):
    """Il y en a des centaines : on ne demande rien, mais ses skills comptent —
    et ce sont les siennes, celles de sa branche."""
    worktree = monde["tmp"] / "worktrees" / "demo_application" / "00234f72"
    skills = worktree / ".bouzecode" / "skills" / "locale"
    skills.mkdir(parents=True)
    (skills / "skill.md").write_text(
        '---\nname: locale\ndescription: "skill de la branche"\n---\n\n# Corps\n',
        encoding="utf-8",
    )

    sortie = _load_project_config(str(worktree))

    assert "worktree" in sortie
    assert "## Skills (1)" in sortie
    assert "AskUserQuestion" not in sortie
    assert "AddProject" not in sortie


def test_un_dossier_equipe_mais_non_enregistre_donne_quand_meme_ses_skills(monde):
    """« Être un projet » et « être équipé » sont deux choses différentes."""
    orphelin = monde["tmp"] / "hors_registre"
    skills = orphelin / ".bouzecode" / "skills" / "utile"
    skills.mkdir(parents=True)
    (skills / "skill.md").write_text(
        '---\nname: utile\ndescription: "une skill quand meme"\n---\n\n# Corps\n',
        encoding="utf-8",
    )

    sortie = _load_project_config(str(orphelin))

    assert "n'est pas enregistré comme projet" in sortie
    assert "## Skills (1)" in sortie
    assert "SkillResearch" in sortie


def test_le_dossier_bouzecode_est_branche_comme_source_de_skills(monde):
    _load_project_config(str(monde["equipe"]))

    assert monde["equipe"] / ".bouzecode" in paths.get_extra_dirs()


def test_dossier_introuvable_le_dit_sans_planter(monde):
    assert "introuvable" in _load_project_config(str(monde["tmp"] / "nexiste_pas"))


# ── cd=True : entrer dans le projet, pas seulement le lire ───────────────────
# Le scénario : un agent spawne dans le worktree d'un AUTRE dépôt, appelle
# LoadProjectConfig sur le projet qui l'intéresse, puis Environment(action='worktree')
# — qui se base sur le cwd et provisionnait donc dans le dépôt de spawn.


def test_cd_deplace_le_process_dans_le_projet(monde, monkeypatch):
    monkeypatch.chdir(monde["tmp"])

    _load_project_config(str(monde["equipe"]), {}, cd=True)

    assert Path.cwd().resolve() == monde["equipe"].resolve()


def test_sans_cd_le_cwd_ne_bouge_pas(monde, monkeypatch):
    """Le déplacement est opt-in : lire un projet reste gratuit et sans effet de bord."""
    monkeypatch.chdir(monde["tmp"])

    _load_project_config(str(monde["equipe"]))

    assert Path.cwd().resolve() == monde["tmp"].resolve()


def test_cd_annonce_le_deplacement_dans_le_briefing(monde, monkeypatch):
    """L'agent doit LIRE qu'il a bougé, sinon il continue à croire qu'il est ailleurs."""
    monkeypatch.chdir(monde["tmp"])

    sortie = _load_project_config(str(monde["equipe"]), {}, cd=True)

    assert "cwd" in sortie.lower()
    assert str(monde["equipe"]) in sortie


def test_cd_ne_ment_pas_sur_l_isolation_worktree(monde, monkeypatch):
    """Entrer dans un projet n'est PAS être isolé : poser BOUZECODE_WORKTREE_ROOT
    armerait à tort le contrat « tu travailles dans un worktree dédié »."""
    monkeypatch.chdir(monde["tmp"])
    monkeypatch.delenv("BOUZECODE_WORKTREE_ROOT", raising=False)

    _load_project_config(str(monde["equipe"]), {}, cd=True)

    assert "BOUZECODE_WORKTREE_ROOT" not in os.environ


def test_cd_sur_dossier_introuvable_ne_deplace_rien(monde, monkeypatch):
    monkeypatch.chdir(monde["tmp"])

    sortie = _load_project_config(str(monde["tmp"] / "nexiste_pas"), {}, cd=True)

    assert "introuvable" in sortie
    assert Path.cwd().resolve() == monde["tmp"].resolve()
