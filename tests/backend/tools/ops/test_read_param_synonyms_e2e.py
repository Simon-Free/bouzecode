# [desc] Conversation tests: Read accepts Snippet's line vocabulary when the conversion is exact, and refuses it when it is not. [/desc]
"""`Snippet` parle `ranges` 1-indexé inclusif, `Read` parle `offset` 0-indexé +
`limit`. Le modèle alterne entre les deux outils sur le même fichier et mélange
les deux vocabulaires : 73 échecs, 137 tours perdus
(`docs/investigations/tool_input_leniency.md`).

La conversion est arithmétiquement exacte — on lit exactement les lignes
demandées, rien n'est deviné — donc elle est acceptée, avec une note pour que le
modèle apprenne le bon nom. Deux choses ne le sont jamais : plusieurs plages
(l'union rendrait des lignes que personne n'a demandées) et `command=`, qui
ferait passer un Read par un chemin d'exécution.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
CLOSE = "C'est fait."


@pytest.fixture
def fichier(tmp_path):
    f = tmp_path / "temp_cinquante.py"
    f.write_text("\n".join(f"ligne {i}" for i in range(1, 51)) + "\n", encoding="utf-8")
    return f


def _run_read(params_xml, user="lis ce fichier"):
    mock = MockLLM([f"je lis.\n{METH}\n<tool_use name=\"Read\" id=\"r1\">{params_xml}</tool_use>",
                    CLOSE])
    result = bouzecode([user], mock_llm=mock)
    return next(m["content"] for m in result.messages
                if m.get("role") == "tool" and m.get("name") == "Read")


# ── conversions exactes acceptées ────────────────────────────────────────────

def test_read_accepts_snippet_ranges_and_says_which_parameter_it_meant(fichier):
    """Appel réel du corpus : Read(ranges=[[10, 20]]) rend bien les lignes 10 à 20, et nomme offset/limit."""
    res = _run_read(f'<param name="file_path">{fichier}</param>'
                    f'<param name="ranges">[[10, 20]]</param>')

    assert "ligne 10" in res and "ligne 20" in res
    assert "ligne 9" not in res and "ligne 21" not in res
    assert "[note] 'ranges' is not a Read parameter" in res
    assert "offset=9, limit=11" in res


def test_read_accepts_start_line_and_end_line(fichier):
    """La convention d'un autre harnais (start_line/end_line) est convertie de la même façon."""
    res = _run_read(f'<param name="file_path">{fichier}</param>'
                    f'<param name="start_line">5</param><param name="end_line">7</param>')

    assert "ligne 5" in res and "ligne 7" in res
    assert "ligne 8" not in res
    assert "offset=4, limit=3" in res


def test_read_ignores_a_stray_label(fichier):
    """`label` appartient à Snippet et n'a aucun sens pour Read : ignoré, signalé, la lecture a lieu."""
    res = _run_read(f'<param name="file_path">{fichier}</param>'
                    f'<param name="range">[1, 3]</param>'
                    f'<param name="label">le début du module</param>')

    assert "ligne 1" in res and "ligne 3" in res
    assert "'label' is not a Read parameter" in res


# ── ce qui doit rester un refus ──────────────────────────────────────────────

def test_read_refuses_several_ranges_and_spells_out_the_two_calls(fichier):
    """Read ne lit qu'une région contiguë : l'union tairait les lignes intercalaires. Refus + les deux appels."""
    res = _run_read(f'<param name="file_path">{fichier}</param>'
                    f'<param name="ranges">[[1, 5], [20, 25]]</param>')

    assert res.startswith("Error:") and "2 ranges" in res
    assert "offset=0, limit=5" in res and "offset=19, limit=6" in res
    assert "ligne 1" not in res  # aucun contenu de fichier n'a été rendu


def test_read_never_routes_a_command_to_execution(fichier, tmp_path):
    """`command=` vise Bash. Router un Read vers l'exécution contournerait tout le chemin de sûreté : refus sec."""
    temoin = tmp_path / "temp_preuve.txt"

    res = _run_read(f'<param name="file_path">{fichier}</param>'
                    f'<param name="command">New-Item -ItemType File "{temoin}"</param>')

    assert res.startswith("Error:") and "Bash" in res
    assert not temoin.exists()  # rien n'a été exécuté
    assert "ligne 1" not in res


def test_read_points_a_recursive_call_at_the_folder_tools(fichier):
    """`recursive=` vise l'exploration d'arborescence : le message aiguille vers Glob/Grep."""
    res = _run_read(f'<param name="file_path">{fichier}</param>'
                    f'<param name="recursive">true</param>')

    assert res.startswith("Error:")
    assert "Glob" in res and "Grep" in res
    assert "GetFolderDescription" not in res   # outil non offert : ne jamais l'aiguiller
