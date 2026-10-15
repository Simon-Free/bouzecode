# [desc] Conversation tests: an interface task only closes on user journeys the session REALLY played; a reviewer KO sends the work back. [/desc]
"""Une interface ne se livre que sur des parcours utilisateur réellement joués.

Essai DeepSeek du 2026-09-24 (« portail des énigmes ») : clôture sur des tests verts, alors
que l'édition effaçait les données et que la réponse s'affichait avant d'être demandée. Ces
conversations passent par la vraie boucle, les vrais outils (Write, Bash) et le vrai
handler de FinalAnswer : seul le modèle est simulé.
"""
from __future__ import annotations

import json

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM


@pytest.fixture(autouse=True)
def _agent_dans_son_depot(tmp_path, monkeypatch):
    """L'agent travaille dans son dépôt : ce qu'il écrit sous tmp_path est l'interface, pas
    un script temporaire (la porte ignore /tmp HORS du répertoire de travail)."""
    monkeypatch.chdir(tmp_path)


DEMANDE_UI = "Fais-moi une page qui présente une énigme puis sa solution."
RECAP = json.dumps({"symptoms": "page d'énigmes", "explanation": "page statique + test"})
REFUS = "CLÔTURE REFUSÉE"


def _config(**over) -> dict:
    cfg = {"require_recap": True, "recap_coding": False, "close_validation": True,
           "model": "claude-sonnet-4-5"}
    cfg.update(over)
    return cfg


def _meth(i: str) -> str:
    return f'<tool_use name="Methodology" id="m{i}"><param name="content">étape {i}</param></tool_use>'


def _write(i: str, chemin, contenu: str) -> str:
    return (f'<tool_use name="Write" id="w{i}"><param name="file_path">{chemin}</param>'
            f'<param name="content">{contenu}</param></tool_use>')


def _bash(i: str, commande: str) -> str:
    return f'<tool_use name="Bash" id="b{i}"><param name="command">{commande}</param></tool_use>'


def _final(i: str, parcours: list | None = None) -> str:
    extra = ("" if parcours is None else
             f'<param name="parcours_verifies">{json.dumps(parcours, ensure_ascii=False)}</param>')
    return (f'<tool_use name="FinalAnswer" id="f{i}"><param name="answer">Page livrée.</param>'
            f'<param name="taches_terminees">["page énigme"]</param>'
            f'<param name="taches_restantes">[]</param><param name="recap">{RECAP}</param>'
            f'{extra}</tool_use>')


def _parcours(preuve: str) -> list:
    return [{"exigence": "présenter l'énigme puis la solution",
             "parcours": "afficher la carte → la solution est masquée → révéler → relire",
             "preuve": preuve}]


def _script_e2e(tmp_path, sortie: str, code: int) -> tuple[str, str]:
    """Un faux runner navigateur : un VRAI script exécuté, dont on choisit la sortie."""
    # Portable : un script Python lancé par l'interpréteur courant (pas de `sh` sous Windows).
    import sys
    script = tmp_path / "e2e_playwright.py"
    return (_write("s", script, f"import sys; print('{sortie}'); sys.exit({code})"),
            f"{sys.executable} {script}")


def _chaine(*commandes: str) -> str:
    """Chaîne shell lancée par le Bash du harnais : `&&` + `| tail` en POSIX ; sous Windows
    (PowerShell 5.1, sans `&&` ni `tail`) `;` + `| Select-Object -Last N`."""
    import os
    if os.name == "nt":
        return " ; ".join(commandes)
    return " && ".join(commandes)


def _refus(result) -> list[str]:
    return [str(m.get("content", "")) for m in result.messages
            if m.get("role") == "tool" and REFUS in str(m.get("content", ""))]


def test_une_preuve_reellement_executee_et_verte_ouvre_la_cloture(tmp_path):
    """Le test navigateur a tourné, vert, après la dernière retouche de la page."""
    ecrire_script, lancer = _script_e2e(tmp_path, "3 passed", 0)
    mock = MockLLM([
        f"{_meth('1')}\n{_write('1', tmp_path / 'app.js', 'montrer()')}\n{ecrire_script}",
        f"{_meth('2')}\n{_bash('1', lancer)}",
        f"{_meth('3')}\n{_final('1', _parcours(lancer))}",
    ])
    result = bouzecode([DEMANDE_UI], mock_llm=mock, config_overrides=_config())

    assert _refus(result) == []
    assert result.state.close_reason == "final_answer"
    assert result.state.final_answer == "Page livrée."


def test_une_petite_correction_sans_interface_n_est_pas_alourdie(tmp_path):
    """Corriger un module Python pour une demande sans interface : clôture directe."""
    mock = MockLLM([
        f"{_meth('1')}\n{_write('1', tmp_path / 'calcul.py', 'def f():\n    return 2')}",
        f"{_meth('2')}\n{_final('1')}",
    ])
    result = bouzecode(["corrige f() qui renvoie 1 au lieu de 2"], mock_llm=mock,
                       config_overrides=_config(close_review=True))

    assert _refus(result) == []
    assert result.state.final_answer == "Page livrée."
    assert mock.side_calls == 0, "aucun relecteur lancé pour une tâche sans interface"


class _LLMAvecRelecteur(MockLLM):
    """Le relecteur est un sous-agent : il répond, dans l'ordre, les verdicts donnés."""

    def __init__(self, responses, verdicts):
        super().__init__(responses)
        self.verdicts = list(verdicts)
        self.demandes_au_relecteur: list[str] = []

    def stream(self, model, system, messages, tool_schemas, config):
        premier = str(messages[0].get("content", "")) if messages else ""
        if (config or {}).get("_depth", 0) > 0 and "RELECTEUR INDÉPENDANT" in premier:
            if len(messages) == 1:  # premier tour d'une NOUVELLE relecture
                self.demandes_au_relecteur.append(premier)
            self.side_call_response = self.verdicts[len(self.demandes_au_relecteur) - 1]
        yield from super().stream(model, system, messages, tool_schemas, config)


def test_un_relecteur_ko_renvoie_le_travail_avec_ses_retours(tmp_path):
    """Preuves en règle, mais le relecteur, qui a testé en utilisateur, trouve un défaut."""
    ecrire_script, lancer = _script_e2e(tmp_path, "3 passed", 0)
    mock = _LLMAvecRelecteur([
        f"{_meth('1')}\n{_write('1', tmp_path / 'index.html', 'v1')}\n{ecrire_script}",
        f"{_meth('2')}\n{_bash('1', lancer)}",
        f"{_meth('3')}\n{_final('1', _parcours(lancer))}",
        f"{_meth('4')}\n{_write('2', tmp_path / 'index.html', 'v2')}",
        f"{_meth('5')}\n{_bash('2', lancer)}",
        f"{_meth('6')}\n{_final('2', _parcours(lancer))}",
    ], verdicts=["La solution est visible avant le clic sur Révéler.\nVERDICT: KO",
                 "Chaque exigence fonctionne.\nVERDICT: OK"])
    result = bouzecode([DEMANDE_UI], mock_llm=mock,
                       config_overrides=_config(close_review=True))

    refus = _refus(result)
    assert len(refus) == 1 and "relecteur indépendant" in refus[0]
    assert "visible avant le clic" in refus[0], "les retours du relecteur reviennent à l'agent"
    assert DEMANDE_UI in mock.demandes_au_relecteur[0], "le relecteur reçoit la demande d'origine"
    assert len(mock.demandes_au_relecteur) == 2
    assert result.state.final_answer == "Page livrée."


def _outil_navigateur(nom: str, rendu: str):
    """Un outil `mcp__chrome-devtools__*` tel que l'agent le voit : il tourne et rend du texte."""
    from bouzecode.backend.core.tool_registry import ToolDef, register_tool, unregister_tool
    register_tool(ToolDef(name=nom, schema={"name": nom, "description": "navigateur",
                                            "input_schema": {"type": "object", "properties": {}}},
                          func=lambda p, c: rendu, read_only=True, concurrent_safe=True))
    return lambda: unregister_tool(nom)


def test_une_preuve_ecrite_en_prose_qui_nomme_l_outil_navigateur_joue_est_acceptee(tmp_path):
    """Essai DeepSeek réel : « click uid=1_4 puis take_snapshot → '2' » désigne un vrai appel."""
    retirer = _outil_navigateur("mcp__chrome-devtools__take_snapshot", "StaticText \"2\"")
    try:
        snapshot = ('<tool_use name="mcp__chrome-devtools__take_snapshot" id="n1">'
                    '<param name="pageId">2</param></tool_use>')
        prose = "mcp__chrome-devtools__click uid=1_4 puis take_snapshot → StaticText '2'"
        mock = MockLLM([
            f"{_meth('1')}\n{_write('1', tmp_path / 'app.js', 'plus()')}",
            f"{_meth('2')}\n{snapshot}",
            f"{_meth('3')}\n{_final('1', _parcours(prose))}",
        ])
        result = bouzecode([DEMANDE_UI], mock_llm=mock, config_overrides=_config())
    finally:
        retirer()

    assert _refus(result) == []
    assert result.state.final_answer == "Page livrée."


def _scraper(tmp_path) -> str:
    """Un vrai script de scraping, écrit par l'agent, dont la sortie compte les énigmes."""
    return _write("p", tmp_path / "scraper.py", "print('310 énigmes écrites')")


def test_une_commande_citee_en_partie_d_une_chaine_reellement_lancee_est_acceptee(tmp_path):
    """Essai 3, tour 36 : le scraper avait tourné dans un `cd … && … | tail`, et la preuve était refusée."""
    ecrire_script, lancer = _script_e2e(tmp_path, "3 passed", 0)
    import os
    import sys
    queue = "Select-Object -Last 3" if os.name == "nt" else "tail -3"
    chaine = _chaine(f"cd {tmp_path}",
                     f"{sys.executable} scraper.py --out data.json 2>&1 | {queue}",
                     "echo fin")
    scrape = [{"exigence": "scraper les énigmes du site",
               "parcours": "lancer le scraper puis relire le JSON",
               "preuve": "python3 scraper.py --out data.json → 310 énigmes, 0 sans réponse"}]
    mock = MockLLM([
        f"{_meth('1')}\n{_write('1', tmp_path / 'index.html', 'v1')}\n{ecrire_script}\n"
        f"{_scraper(tmp_path)}",
        f"{_meth('2')}\n{_bash('1', chaine)}\n{_bash('2', lancer)}",
        f"{_meth('3')}\n{_final('1', _parcours(lancer) + scrape)}",
    ])
    result = bouzecode([DEMANDE_UI], mock_llm=mock, config_overrides=_config())

    assert _refus(result) == []
    assert result.state.final_answer == "Page livrée."
