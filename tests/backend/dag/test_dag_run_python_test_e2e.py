# [desc] Conversation : un lot « Write du fichier de test + RunPythonTest » sans depends_on lance le test APRÈS l'écriture (plus de « cible introuvable ») [/desc]
"""Session 859446f8a8bf (B4, 2026-10-14) : le modèle écrit un fichier de test et le lance dans le
même lot, sans `depends_on` ; RunPythonTest partait en parallèle du Write et répondait « cible
introuvable »."""
from __future__ import annotations

import os

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from tests.pytest_imbrique import options_etanches

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


def test_test_ecrit_dans_le_meme_lot_est_trouve_et_joue(tmp_path, monkeypatch):
    """Write puis RunPythonTest du même fichier, même lot, sans depends_on : le test tourne."""
    monkeypatch.setenv("BZ_TESTD", "0")
    monkeypatch.setenv("PYTEST_ADDOPTS", " ".join(options_etanches(tmp_path)))
    projet = tmp_path / "projet"
    projet.mkdir()
    (projet / "pyproject.toml").write_text("[project]\nname='jetable'\nversion='0'\n", encoding="utf-8")
    cible = (projet / "test_tout_neuf.py").as_posix()
    ecriture = (f'<tool_use name="Write" id="w1"><param name="file_path">{cible}</param>'
                f'<param name="content">def test_neuf():\n    assert True\n</param></tool_use>')
    lancement = (f'<tool_use name="RunPythonTest" id="t1"><param name="targets">["{cible}"]</param>'
                 f'<param name="parallel">off</param></tool_use>')
    result = bouzecode(["écris le test et lance-le"],
                  mock_llm=MockLLM([f"{METH}\n{ecriture}\n{lancement}", "C'est fait."]))
    sorties = [m["content"] for m in result.messages
               if m.get("role") == "tool" and m.get("name") == "RunPythonTest"]
    assert sorties and "1 passed" in sorties[0], sorties
    assert "introuvable" not in sorties[0]
    assert os.path.exists(cible)
