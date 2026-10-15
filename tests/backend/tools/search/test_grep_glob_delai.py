"""Grep/Glob sur un gros arbre : un délai dépassé rend les résultats partiels, pas une trace.

Constat sur les sessions réelles (poste Windows) : sur `PycharmProjects\\demo`, `~/.claude`
ou `~/.bouzecode`, rg était tué à 30 s et l'agent recevait
« Error: Command '['rg', '--no-heading', ... ]' timed out after 30 seconds » — une ligne de
commande de 400 caractères, zéro résultat, et aucune piste pour réduire la recherche.
"""
import subprocess

from bouzecode.backend.tools.ops import grep_glob


def _trop_long(sortie):
    def _run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"), output=sortie)
    return _run


def test_grep_rend_les_resultats_partiels_et_un_conseil(tmp_path, monkeypatch):
    monkeypatch.setattr(grep_glob, "_has_rg", lambda: True)
    monkeypatch.setattr(grep_glob.subprocess, "run", _trop_long(b"a.py:1:LLMConnector\n"))
    out = grep_glob._grep("LLMConnector", str(tmp_path))
    assert "a.py:1:LLMConnector" in out
    assert "partiel" in out
    assert "'--no-heading'" not in out


def test_glob_rend_les_resultats_partiels(tmp_path, monkeypatch):
    monkeypatch.setattr(grep_glob, "_has_rg", lambda: True)
    monkeypatch.setattr(grep_glob.subprocess, "run", _trop_long("x/a.py\nx/b.py\n"))
    out = grep_glob._glob("*.py", str(tmp_path))
    assert "x/a.py" in out and "partiel" in out


def test_le_delai_de_rg_nest_plus_de_30_secondes(tmp_path, monkeypatch):
    vus = []

    class _R:
        stdout, stderr, returncode = "", "", 1

    def _run(cmd, **kwargs):
        vus.append(kwargs.get("timeout"))
        return _R()

    monkeypatch.setattr(grep_glob, "_has_rg", lambda: True)
    monkeypatch.setattr(grep_glob.subprocess, "run", _run)
    grep_glob._grep("x", str(tmp_path))
    assert vus and min(vus) >= 120
