# [desc] Read d'un gros fichier sans plage rend son plan (symboles + lignes) ; max_tool_output plafonne enfin tout résultat d'outil, sortie complète sauvée dans un fichier. [/desc]
"""Rapport docs/reduction_tokens §2.1 et §3.2 (correctifs points 5b et 7).

- Un `Read` sans plage d'un fichier inconnu de 400+ lignes arrivait entier (jusqu'à 50 k car.),
  puis recopié dans la note, ou lu en tranches successives, un tour par tranche.
- `max_tool_output` (32 000) était défini dans la config et lu nulle part.
"""
from __future__ import annotations

import re

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

_METH = '<tool_use name="Methodology" id="m1"><param name="content">lire</param></tool_use>'


def _read(chemin, **plage) -> str:
    params = "".join(f'<param name="{k}">{v}</param>' for k, v in plage.items())
    mock = MockLLM([
        f'{_METH}<tool_use name="Read" id="r1"><param name="file_path">{chemin}</param>{params}</tool_use>',
        "Lu.",
    ])
    result = bouzecode(["lis"], mock_llm=mock, config_overrides={"enforce_tests": False})
    return next(m["content"] for m in result.messages if m.get("role") == "tool" and m.get("name") == "Read")


def _gros_module(tmp_path):
    corps = ["import os", ""]
    for i in range(80):
        corps += [f"def fonction_{i}(x):", f"    return x + {i}", "", ""]
    corps += ["class Service:", "    def demarrer(self):", "        return 'ok'", ""]
    chemin = tmp_path / "module.py"
    chemin.write_text("\n".join(corps) + "\n", encoding="utf-8")
    return chemin


def test_read_sans_plage_d_un_gros_fichier_rend_son_plan(tmp_path):
    chemin = _gros_module(tmp_path)

    lu = _read(chemin)

    assert "326 lignes" in lu and "Plan :" in lu
    assert "def fonction_79  L319-320" in lu
    assert "class Service  L323-325" in lu
    assert "def Service.demarrer  L324-325" in lu
    assert re.search(r"^\s+120\t", lu, re.M), "les 120 premières lignes sont là"
    assert not re.search(r"^\s+121\t", lu, re.M), "pas au-delà"
    assert 'Read(file_path, offset=0, limit=326)' in lu


def test_read_avec_plage_reste_un_read_normal(tmp_path):
    chemin = _gros_module(tmp_path)

    lu = _read(chemin, offset=318, limit=3)

    assert lu.split("\n")[0].endswith("def fonction_79(x):")
    assert "Plan :" not in lu


def test_max_tool_output_plafonne_un_resultat_et_sauve_la_sortie_complete(tmp_path, monkeypatch):
    monkeypatch.setenv("BOUZECODE_TOOL_OUTPUT_DIR", str(tmp_path / "sorties"))
    chemin = tmp_path / "donnees.txt"
    chemin.write_text("\n".join(f"ligne {i:04d} " + "x" * 50 for i in range(1000)), encoding="utf-8")

    lu = _read(chemin, offset=0, limit=1000)

    sauve = re.search(r'Read\(file_path="([^"]+)"\)', lu).group(1)
    #  Le marqueur cite le chemin de sauvegarde, dont la longueur dépend du tmp du worker.
    assert len(lu) - len(sauve) < 32000 + 400, "plafond max_tool_output (32 000 car.) + marqueur"
    assert "ligne 0000" in lu and "ligne 0999" in lu, "tête et queue gardées"
    assert "ligne 0500" in open(sauve, encoding="utf-8").read()
