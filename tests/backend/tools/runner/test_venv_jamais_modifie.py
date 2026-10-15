# [desc] RunPythonTest dans un projet qui a un venv : `<python du venv> -m pytest` direct, jamais `uv run` sans `--no-sync` ; Scripts/ et site-packages inchangés après le run [/desc]
"""Le 2026-10-14, `uv run --directory demoapp_clone pytest` a synchronisé le venv partagé de
demoapp_clone (paquet du projet et son `.exe` réinstallés, `cryptography` à moitié désinstallé).

Vrai venv : le `.venv` du petit projet est une JONCTION vers le venv de ce run (aucun `.exe`
créé ni copié) ; la jonction est retirée par la fixture elle-même (`os.rmdir` ne retire que le
lien), avant tout nettoyage de tmp qui pourrait la suivre."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from bouzecode.backend.tools.ops.test_runner import run_python_test

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="jonction NTFS")

_VENV = Path(sys.prefix)
_SURVEILLES = [_VENV / "Scripts", _VENV / "Lib" / "site-packages", _VENV / "pyvenv.cfg",
               _VENV / "Lib" / "site-packages" / "_editable_impl_bouzecode.pth"]


def _mtimes() -> dict[str, float]:
    return {str(p): p.stat().st_mtime for p in _SURVEILLES if p.exists()}


@pytest.fixture
def projet_avec_venv(tmp_path, monkeypatch):
    import _winapi
    racine = tmp_path / "projet"
    racine.mkdir()
    (racine / "pyproject.toml").write_text("[project]\nname = 'mini'\nversion = '0'\n", encoding="utf-8")
    (racine / "test_mini.py").write_text("def test_un():\n    pass\n\ndef test_deux():\n    pass\n",
                                         encoding="utf-8")
    _winapi.CreateJunction(str(_VENV), str(racine / ".venv"))
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    yield racine
    os.rmdir(racine / ".venv")  # le lien seulement, jamais le venv visé


def _commande(resultat: str) -> str:
    return next(l for l in resultat.splitlines() if l.startswith("$ "))


@pytest.mark.parametrize("parallel", ["off", "2"])
def test_venv_du_projet_execute_directement_et_jamais_modifie(projet_avec_venv, parallel):
    avant = _mtimes()
    resultat = run_python_test(targets=[str(projet_avec_venv / "test_mini.py")],
                               parallel=parallel, timeout=120)
    commande = _commande(resultat)
    assert "uv run" not in commande, commande
    assert commande.startswith(f"$ {projet_avec_venv / '.venv' / 'Scripts' / 'python.exe'} -m pytest")
    assert "2 passed" in resultat, resultat
    assert _mtimes() == avant


def test_sans_venv_de_projet_le_venv_du_process_sert_sans_uv(tmp_path, monkeypatch):
    racine = tmp_path / "nu"
    racine.mkdir()
    (racine / "pyproject.toml").write_text("[project]\nname = 'nu'\nversion = '0'\n", encoding="utf-8")
    (racine / "test_nu.py").write_text("def test_un():\n    pass\n", encoding="utf-8")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    avant = _mtimes()
    resultat = run_python_test(targets=[str(racine / "test_nu.py")], parallel="off",
                               no_sync=False, timeout=120)
    commande = _commande(resultat)
    assert "uv run" not in commande or "--no-sync" in commande, commande
    assert "1 passed" in resultat, resultat
    assert not (racine / ".venv").exists()
    assert _mtimes() == avant
