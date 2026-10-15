# [desc] Conversation : sur une longue sortie pytest, le résultat RunPythonTest garde le verdict, la liste FAILED et l'assertion de l'échec. [/desc]
"""Le modèle voit pourquoi ses tests échouent sans relire le fichier de sortie complet.

Autopsie 9f14d1810dd5 (2026-10-05) : la troncature tête + queue coupait au milieu la ligne
`E   AssertionError` d'un échec, et l'agent relisait quatre fois le fichier complet par Bash.
Ici, un VRAI pytest tourne sur 400 tests verts puis un échec dont la trace est longue (gros
corps de fonction, beaucoup de sortie capturée) : l'assertion était exactement au milieu.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
CLOSE = "C'est fait."

TESTS_LONGS = (
    "import pytest\n\n"
    "@pytest.mark.parametrize('n', range(400))\n"
    "def test_vert(n):\n    assert n >= 0\n\n"
    "def test_total_a_la_fin():\n"
    + "".join(f"    etape_{i} = {i}  # préparation {i}\n" for i in range(150))
    + "    for i in range(200):\n"
      "        print(f'journal de préparation, ligne {i} : tout va bien jusque-là')\n"
      "    total = 41\n"
      "    assert total == 42, 'TOTAL_ATTENDU_42'\n"
)


@pytest.fixture(autouse=True)
def _runpythontest_actif(tmp_path, monkeypatch):
    from bouzecode.backend.core.tool_registry import enable_tool
    enable_tool("RunPythonTest")
    monkeypatch.setenv("BOUZECODE_TOOL_OUTPUT_DIR", str(tmp_path / "tool_outputs"))


def _runtest(cible: str) -> str:
    return (f'<tool_use name="RunPythonTest" id="rpt1"><param name="targets">["{cible}"]</param>'
            f'<param name="parallel">off</param><param name="no_sync">true</param></tool_use>')


def _resultat_runner(result) -> str:
    for message in result.messages:
        contenu = message.get("content")
        if message.get("role") == "tool" and isinstance(contenu, str) and "[RunPythonTest]" in contenu:
            return contenu
    raise AssertionError("résultat RunPythonTest introuvable")


def test_long_run_keeps_the_failing_assertion_in_the_tool_result(tmp_path):
    """400 tests verts puis un échec à la trace longue : le verdict, FAILED et l'assertion restent visibles."""
    fichier = tmp_path / "test_echec_au_milieu_de_la_trace.py"  # basename unique dans la suite
    fichier.write_text(TESTS_LONGS, encoding="utf-8")
    cible = str(fichier).replace("\\", "/")

    result = bouzecode(["lance les tests"], mock_llm=MockLLM([f"{METH}\n{_runtest(cible)}", CLOSE]))
    sortie = _resultat_runner(result)

    corps = sortie.split("─" * 60, 1)[1]
    assert "1 failed, 400 passed" in corps, corps
    assert "FAILED " in corps and "::test_total_a_la_fin" in corps, corps
    assert "TOTAL_ATTENDU_42" in corps, corps
    assert "assert 41 == 42" in corps, corps
    assert "full output saved to:" in corps, corps
    assert len(corps) <= 8000, len(corps)  # le budget de caractères existant
    # Le fichier complet garde tout, y compris la sortie capturée coupée ici.
    chemin = corps.split("full output saved to: ", 1)[1].split("]", 1)[0]
    complet = open(chemin, encoding="utf-8").read()
    assert "ligne 199 : tout va bien" in complet
    assert "etape_75 = 75" in complet
