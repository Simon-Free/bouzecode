# [desc] Porte « parcours vérifiés » : les faux refus de l'essai du 2026-09-25 (preuve dans le même lot, sortie vide, enveloppe HOME=…, sous-shell, script qui lance Playwright, enfant sans interface). [/desc]
"""Essai DeepSeek du 2026-09-25 (« portail des énigmes »), clôtures rejouées : la racine
6bafe9cd a essuyé quatre refus alors que ses recettes navigateur étaient vertes (20/20, 7/7,
5/5), puis a clos « NON prouvés » au plafond ; l'enfant 625883f1, qui n'avait écrit aucune
interface, aussi. Ces conversations passent par la vraie boucle et le vrai FinalAnswer."""
from __future__ import annotations

import json
import sys

import pytest

from bouzecode.backend.agent import close_parcours
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

# 998 s mesurees pour ce SEUL module (run `-n 4` du 2026-09-28) : chacun de ses tests rejoue
# une conversation entiere dans la vraie boucle d'agent. Aucun jeton de tests/auto_markers.py
# ne l'attrape (pas de pytest imbrique, pas de chronometre, pas d'appel au gateway reel), donc
# le marqueur est pose ICI, a la main, pour le sortir de la voie par defaut. `pytest -m ""`
# (la commande de suite complete, cf. pyproject.toml) le rejoue.
pytestmark = pytest.mark.slow

#  Ces recettes sont des scripts `sh`/`bash` lancés pour de vrai par l'outil Bash. Sous Windows
#  il exécute PowerShell (et le `bash` du PATH est celui de WSL) : la recette échoue avant que
#  la porte ne juge quoi que ce soit. Même convention que test_bash_processus_a_la_cloture.
recette_posix = pytest.mark.skipif(
    sys.platform == "win32", reason="recette sh/bash : l'outil Bash exécute PowerShell sous Windows")


@pytest.fixture(autouse=True)
def _agent_dans_son_depot(tmp_path, monkeypatch):
    """L'agent travaille dans son dépôt : tmp_path est son répertoire de travail."""
    monkeypatch.chdir(tmp_path)


DEMANDE_UI ="Fais-moi une page qui présente une énigme puis sa solution."
RECAP = json.dumps({"symptoms": "page d'énigmes", "explanation": "page statique + test"})
REFUS = "CLÔTURE REFUSÉE par le validateur"


def _config() -> dict:
    return {"require_recap": True, "recap_coding": False, "close_validation": True,
            "model": "claude-sonnet-4-5"}


def _meth(i: str) -> str:
    return f'<tool_use name="Methodology" id="m{i}"><param name="content">étape {i}</param></tool_use>'


def _write(i: str, chemin, contenu: str) -> str:
    return (f'<tool_use name="Write" id="w{i}"><param name="file_path">{chemin}</param>'
            f'<param name="content">{contenu}</param></tool_use>')


def _bash(i: str, commande: str) -> str:
    return f'<tool_use name="Bash" id="b{i}"><param name="command">{commande}</param></tool_use>'


def _final(i: str, preuve: str) -> str:
    parcours = [{"exigence": "présenter l'énigme puis la solution",
                 "parcours": "afficher la carte → révéler la solution → relire", "preuve": preuve}]
    return (f'<tool_use name="FinalAnswer" id="f{i}"><param name="answer">Page livrée.</param>'
            f'<param name="taches_terminees">["page énigme"]</param>'
            f'<param name="taches_restantes">[]</param><param name="recap">{RECAP}</param>'
            f'<param name="parcours_verifies">{json.dumps(parcours, ensure_ascii=False)}</param>'
            '</tool_use>')


def _refus(result) -> list[str]:
    return [str(m.get("content", "")) for m in result.messages
            if m.get("role") == "tool" and REFUS in str(m.get("content", ""))]


@recette_posix
def test_une_recette_jouee_dans_le_lot_de_cloture_n_est_pas_jugee_echouee(tmp_path):
    """Recette lancée puis FinalAnswer dans le MÊME lot : la porte lit son vrai résultat."""
    script = tmp_path / "e2e_playwright.sh"
    mock = MockLLM([
        f"{_meth('1')}\n{_write('1', tmp_path / 'index.html', '<h1>x</h1>')}\n"
        f"{_write('2', script, 'echo 20/20 OK')}",
        f"{_meth('2')}\n{_bash('1', f'sh {script}')}\n{_final('1', f'sh {script}')}",
        f"{_meth('3')}\n{_final('2', f'sh {script}')}",
        f"{_meth('4')}\n{_final('3', f'sh {script}')}",
    ])
    result = bouzecode([DEMANDE_UI], mock_llm=mock, config_overrides=_config())

    assert _refus(result) == [], _refus(result)
    assert result.state.final_answer == "Page livrée."


@recette_posix
def test_une_recette_shell_qui_lance_un_script_playwright_prouve_le_navigateur(tmp_path):
    """`bash all.sh` n'écrit pas « playwright » : c'est le script qu'il lance qui pilote le navigateur."""
    smoke = tmp_path / "smoke.js"
    recette = tmp_path / "all.sh"
    mock = MockLLM([
        f"{_meth('1')}\n{_write('1', tmp_path / 'index.html', '<h1>x</h1>')}\n"
        f"{_write('2', smoke, '// pilote chromium via playwright')}\n"
        f"{_write('3', recette, f'node {smoke}; echo 20/20 OK')}",
        f"{_meth('2')}\n{_bash('1', f'bash {recette} 8802 2>&1 | tail -40')}",
        f"{_meth('3')}\n{_final('1', f'bash {recette} 8802 2>&1 | tail -40 → 20/20 OK')}",
        f"{_meth('4')}\n{_final('2', f'bash {recette} 8802')}",
        f"{_meth('5')}\n{_final('3', f'bash {recette} 8802')}",
    ])
    result = bouzecode([DEMANDE_UI], mock_llm=mock, config_overrides=_config())

    assert _refus(result) == [], _refus(result)


@recette_posix
def test_une_recette_sans_navigateur_reste_refusee(tmp_path):
    """Contrôle : la même recette, dont les scripts ne pilotent aucun navigateur, ne prouve rien."""
    smoke = tmp_path / "smoke.js"
    recette = tmp_path / "all.sh"
    mock = MockLLM([
        f"{_meth('1')}\n{_write('1', tmp_path / 'index.html', '<h1>x</h1>')}\n"
        f"{_write('2', smoke, 'console.log(1)')}\n{_write('3', recette, f'node {smoke}')}",
        f"{_meth('2')}\n{_bash('1', f'bash {recette}')}",
        f"{_meth('3')}\n{_final('1', f'bash {recette}')}",
        f"{_meth('4')}\n{_final('2', f'bash {recette}')}",
        f"{_meth('5')}\n{_final('3', f'bash {recette}')}",
        f"{_meth('6')}\n{_final('4', f'bash {recette}')}",
    ])
    result = bouzecode([DEMANDE_UI], mock_llm=mock, config_overrides=_config())

    assert "aucun parcours n'est prouvé par un navigateur" in _refus(result)[0]


def test_une_commande_citee_avec_ses_variables_d_environnement_est_reconnue(tmp_path):
    """« HOME=… BASE=… node figures.js → 7/7 OK » désigne bien le `node figures.js` lancé."""
    script = tmp_path / "figures_playwright.js"
    commande = f"HOME={tmp_path} BASE=http://127.0.0.1:8795 node {script}"
    mock = MockLLM([
        f"{_meth('1')}\n{_write('1', tmp_path / 'index.html', '<h1>x</h1>')}\n"
        f"{_write('2', script, 'console.log(7)')}",
        f"{_meth('2')}\n{_bash('1', f'cd {tmp_path}; {commande}; echo fin')}",
        f"{_meth('3')}\n{_final('1', f'{commande} → 7/7 OK')}",
        f"{_meth('4')}\n{_final('2', commande)}",
        f"{_meth('5')}\n{_final('3', commande)}",
    ])
    result = bouzecode([DEMANDE_UI], mock_llm=mock, config_overrides=_config())

    assert _refus(result) == [], _refus(result)


@recette_posix
def test_un_serveur_lance_en_sous_shell_et_en_fond_est_reconnu(tmp_path):
    """« python3 serve.py --port 8798 & » cité, « (python3 serve.py --port 8798 &) » lancé."""
    serveur = tmp_path / "serve.py"
    e2e = tmp_path / "e2e_playwright.sh"
    mock = MockLLM([
        f"{_meth('1')}\n{_write('1', tmp_path / 'index.html', '<h1>x</h1>')}\n"
        f"{_write('2', serveur, 'print(1)')}\n{_write('3', e2e, 'echo 5/5 OK')}",
        f"{_meth('2')}\n{_bash('1', f'(python3 {serveur} --port 8798 > /dev/null 2>&1 &) && sh {e2e}')}",
        f"{_meth('3')}\n{_final('1', f'python3 {serveur} --port 8798 & puis sh {e2e} → 5/5 OK')}",
        f"{_meth('4')}\n{_final('2', f'sh {e2e}')}",
        f"{_meth('5')}\n{_final('3', f'sh {e2e}')}",
    ])
    result = bouzecode([DEMANDE_UI], mock_llm=mock, config_overrides=_config())

    assert _refus(result) == [], _refus(result)


def test_un_enfant_qui_n_ecrit_aucune_interface_n_est_pas_soumis_a_la_porte(tmp_path, monkeypatch):
    """Brief d'un parent qui évoque « l'UI » ; l'enfant ne livre que du Python : pas de parcours exigé."""
    monkeypatch.setenv("BOUZECODE_PARENT", "6bafe9cd5ee7")
    monkeypatch.delenv("BOUZECODE_BRIEF_HUMAIN", raising=False)
    brief = "Corrige le scraper. L'UI affichera « réponse à vérifier » (ce n'est pas ton périmètre)."
    mock = MockLLM([
        f"{_meth('1')}\n{_write('1', tmp_path / 'scraper.py', 'x = 1')}",
        f"{_meth('2')}\n{_final('1', 'rien')}",
    ])
    result = bouzecode([brief], mock_llm=mock, config_overrides=_config())

    assert _refus(result) == []
    assert result.state.final_answer == "Page livrée."


@pytest.mark.parametrize("parent, brief_humain", [
    ("", ""), ("dispatcher:manual", ""),
    #  Tâche du Bureau lancée par l'assistant : il en est le parent (réveil), mais le prompt est
    #  la tâche de l'humain — la porte s'applique comme pour un lancement depuis l'écran.
    ("a55157a47000", "1"),
])
def test_le_meme_brief_lance_par_l_utilisateur_reste_soumis_a_la_porte(
        tmp_path, monkeypatch, parent, brief_humain):
    """Contrôle : lancé par l'utilisateur, le même travail demandé « avec UI » reste contrôlé."""
    monkeypatch.setenv("BOUZECODE_PARENT", parent)
    monkeypatch.setenv("BOUZECODE_BRIEF_HUMAIN", brief_humain)
    brief = "Corrige le scraper. L'UI affichera « réponse à vérifier »."
    mock = MockLLM([
        f"{_meth('1')}\n{_write('1', tmp_path / 'scraper.py', 'x = 1')}",
        f"{_meth('2')}\n{_final('1', 'rien')}",
        f"{_meth('3')}\n{_final('2', 'rien')}",
        f"{_meth('4')}\n{_final('3', 'rien')}",
        f"{_meth('5')}\n{_final('4', 'rien')}",
    ])
    result = bouzecode([brief], mock_llm=mock, config_overrides=_config())

    assert _refus(result)


def test_une_execution_sans_sortie_ni_marqueur_d_echec_est_verte():
    """Un appel exécuté dont la sortie est vide n'a pas échoué ; un `[exited code=2]` si."""
    def session(sortie: str) -> list:
        return [
            {"role": "user", "content": "fais une page"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "w", "name": "Write", "input": {"file_path": "/p/index.html", "content": "x"}},
                {"id": "b", "name": "Bash", "input": {"command": "npx playwright test"}}]},
            {"role": "tool", "tool_call_id": "w", "content": "Created /p/index.html"},
            {"role": "tool", "tool_call_id": "b", "content": sortie},
        ]
    parcours = [{"exigence": "voir la page", "parcours": "ouvrir", "preuve": "npx playwright test"}]

    assert close_parcours.manques(parcours, session("")) == []
    assert "a échoué" in close_parcours.manques(parcours, session("[exited code=2]"))[0]
