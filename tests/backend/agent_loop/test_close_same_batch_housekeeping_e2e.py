# [desc] Clôture dans le même lot : le ménage ne bloque plus, et le refus relève les résultats qu'il demande de lire. [/desc]
"""Clôture dans le même lot qu'un outil : ce que les ~30 refus réels ont appris.

Relevé sur les sessions opus-5 du poste Windows (09/09 → 25/09) : 17 refus sur 34 pour
un lot `Environment(cleanup)` + FinalAnswer seul, un pour `DisableChromeDevtools`, le
reste pour un commit Bash (parfois avec `integrate`). Deux défauts :

- rien à lire dans le résultat d'un rangement réussi : ni `Rangé : worktree … retiré`
  ni `chrome-devtools stopped` ne peuvent contredire une réponse — le refus coûtait un
  tour, et souvent DEUX, le modèle refaisant un `git worktree list` pour « vérifier » ;
- quand le refus est fondé (commit, intégration), le modèle ne trouvait pas les
  résultats : « Les résultats du Bash de commit ne sont pas lisibles » (28dcaf81),
  « le message système dit ci-dessous mais je n'ai pas de bloc de résultats »
  (a3b38124). Le refus porte désormais lui-même le relevé de chaque résultat.
"""
from __future__ import annotations

import sys

import pytest

from bouzecode.backend.core.tool_registry import (
    ToolDef, enable_tool, get_tool, register_tool, unregister_tool,
)
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
ANSWER = "Corrigé, commité (ef3ee4f4) et intégré dans develop."
FINAL = ('<tool_use name="FinalAnswer" id="f1">'
         f'<param name="answer">{ANSWER}</param>'
         '<param name="taches_terminees">[]</param>'
         '<param name="taches_restantes">[]</param></tool_use>')
CLEANUP = '<tool_use name="Environment" id="e2"><param name="action">cleanup</param></tool_use>'
INTEGRATE = '<tool_use name="Environment" id="e1"><param name="action">integrate</param></tool_use>'
DISABLE = '<tool_use name="DisableChromeDevtools" id="d1"></tool_use>'

# Résultats réels (3f364511 tours 35-36, 1532a904 tour 58).
RANGE = ("Rangé : worktree C:\\Users\\x\\.bouzecode\\worktrees\\bouzecode\\solo-2 retiré et "
         "branche agent/solo-2 supprimée. Tu es dans C:\\Users\\x\\demo\\bouzecode — "
         "l'ancien chemin n'existe plus, n'y écris plus.")
MERGE = ("Merge propre : ta branche agent/solo-2 est intégrée dans develop. Tu es maintenant "
         "dans C:\\Users\\x\\demo\\bouzecode.")
REFUS_RANGEMENT = ("Refusé : ton travail n'est pas intégré (état 'active'). Ranger maintenant "
                   "DÉTRUIRAIT du code que personne d'autre n'a.")
CHROME_OFF = "chrome-devtools stopped for this agent; Chrome closed. No agent left using it."


@pytest.fixture
def environment(monkeypatch):
    """Environment réel sans git ni ticket : rend, par action, le texte réel du poste."""
    reponses = {"cleanup": RANGE, "integrate": MERGE}
    monkeypatch.setattr(get_tool("Environment"), "func",
                        lambda p, c: reponses[p.get("action")])
    enable_tool("Environment")
    return reponses


@pytest.fixture
def chrome_off():
    deja = get_tool("DisableChromeDevtools")
    register_tool(ToolDef(name="DisableChromeDevtools",
                          schema={"name": "DisableChromeDevtools", "description": "stop",
                                  "input_schema": {"type": "object", "properties": {}}},
                          func=lambda p, c: CHROME_OFF))
    enable_tool("DisableChromeDevtools")
    yield
    if deja is None:
        unregister_tool("DisableChromeDevtools")
    else:
        register_tool(deja)


_MARQUE = "ta clôture n'a PAS été acceptée"


def _refus(result):
    """Le texte de chaque avis de refus — SANS le résultat auquel il est accroché (le
    résultat de FinalAnswer, qui recopie la réponse et ses shas)."""
    return [_MARQUE + str(m.get("content", "")).split(_MARQUE, 1)[1] for m in result.messages
            if _MARQUE in str(m.get("content", ""))]


def _bash(commande: str, ident: str = "b1") -> str:
    return (f'<tool_use name="Bash" id="{ident}"><param name="command">{commande}'
            '</param></tool_use>')


def test_un_rangement_reussi_ne_retient_pas_la_cloture(environment):
    """ecb82e34, 64c06ab0, 3baa9a6b, 70ac631d… : cleanup + FinalAnswer, une fois intégré."""
    mock = MockLLM([f"{METH}\n{CLEANUP}\n{FINAL}", "JAMAIS CONSOMMÉ"])
    result = bouzecode(["corrige puis livre"], mock_llm=mock)

    assert _refus(result) == []
    assert result.state.close_reason == "final_answer"
    assert result.state.final_answer == ANSWER
    assert len(mock.recorded_calls) == 1


def test_eteindre_chrome_ne_retient_pas_la_cloture(chrome_off):
    """1532a904 tour 58 : DisableChromeDevtools ne peut rien dire du travail CSS livré."""
    mock = MockLLM([f"{METH}\n{DISABLE}\n{FINAL}", "JAMAIS CONSOMMÉ"])
    result = bouzecode(["refonds le bureau"], mock_llm=mock)

    assert _refus(result) == []
    assert result.state.close_reason == "final_answer"


def test_un_rangement_refuse_retient_toujours_la_cloture(environment):
    """« Refusé : pas intégré » contredit « intégré dans develop » : là, il faut lire."""
    environment["cleanup"] = REFUS_RANGEMENT
    mock = MockLLM([f"{METH}\n{CLEANUP}\n{FINAL}", f"{METH}\n{FINAL}"])
    result = bouzecode(["livre"], mock_llm=mock)

    refus = _refus(result)
    assert len(refus) == 1
    assert "pas intégré" in refus[0], "le refus relève le résultat qu'il demande de lire"


def test_commit_et_integration_retiennent_la_cloture_et_sont_releves(environment):
    """3f364511 tour 35 : commit + integrate + cleanup + FinalAnswer dans un seul lot.

    Le commit et l'intégration comptent (la réponse cite leur sha et leur merge) : refus.
    Le rangement réussi, lui, n'est plus cité comme une lecture à faire."""
    commit = _bash("echo [agent/solo-2 ef3ee4f4] feat: lien Teams coupe par defaut")
    mock = MockLLM([f"{METH}\n{commit}\n{INTEGRATE}\n{CLEANUP}\n{FINAL}", f"{METH}\n{FINAL}"])
    result = bouzecode(["livre"], mock_llm=mock)

    refus = _refus(result)
    assert len(refus) == 1
    avis = refus[0]
    assert "ef3ee4f4" in avis, "extrait du résultat du commit dans l'avis même"
    assert "Merge propre" in avis, "extrait du résultat de l'intégration"
    assert "Rangé" not in avis, "un rangement réussi n'est pas une lecture exigée"
    assert "AU-DESSUS" in avis and "ci-dessous" not in avis
    assert "ONT été exécutés" in avis and "ne les rejoue PAS" in avis
    assert result.state.final_answer == ANSWER


def test_le_releve_dit_le_code_de_sortie_d_un_bash_rouge():
    """Le statut d'abord : un commit rouge se voit sans avoir à fouiller la sortie."""
    mock = MockLLM([f"{METH}\n{_bash('echo nothing to commit; exit 3')}\n{FINAL}",
                    f"{METH}\n{FINAL}"])
    result = bouzecode(["livre"], mock_llm=mock)

    avis = _refus(result)[0]
    assert "code de sortie 3" in avis
    assert "nothing to commit" in avis


def test_le_releve_d_une_longue_sortie_garde_le_debut_et_la_fin():
    """Suite de tests : le verdict est en FIN de sortie, l'en-tête au début."""
    # L'outil Bash exécute PowerShell sous Windows : même sortie, syntaxe du shell réel.
    longue = ('1..60 | ForEach-Object { "ligne$_" }; "80 passed"' if sys.platform == "win32"
              else "for i in $(seq 1 60); do echo ligne$i; done; echo 80 passed")
    mock = MockLLM([f"{METH}\n{_bash(longue)}\n{FINAL}", f"{METH}\n{FINAL}"])
    result = bouzecode(["livre"], mock_llm=mock)

    avis = _refus(result)[0]
    assert "ligne1" in avis and "80 passed" in avis
    assert "ligne30" not in avis, "le relevé est un extrait, pas une recopie"
