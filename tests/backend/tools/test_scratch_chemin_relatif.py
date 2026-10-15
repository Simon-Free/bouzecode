"""Un fichier scratch écrit sous un chemin ABSOLU reste joignable sous son nom court.

Constat sur les sessions réelles (poste Windows) — le motif revient dans une dizaine de sessions :
    Write(file_path="C:\\...\\demo\\bouzecode\\temp_sonde_rapport.py", temp=True)
    Bash("cd C:\\...\\demo\\bouzecode ; uv run --no-sync python temp_sonde_rapport.py")
    → can't open file '...\\temp_sonde_rapport.py': [Errno 2] No such file or directory
La substitution ne connaissait que le chemin logique EXACT. Elle reconnaît désormais le nom
court (`temp_x.py`, `.\\temp_x.py`, `./temp_x.py`) et un chemin deviné qui se termine par ce
nom mais n'existe pas — tant que le nom est sans ambiguïté et qu'aucun vrai fichier ne le porte.
"""
import uuid

import pytest

from bouzecode.backend.tools.ops import scratch
from bouzecode.backend.tools.ops.file_ops import _write
from bouzecode.backend.tools.ops.shell_search import _substitute_scratch_paths


@pytest.fixture(autouse=True)
def _session():
    scratch.set_scratch_session(f"test-{uuid.uuid4().hex}")
    yield
    scratch.cleanup_scratch()


def _temp(tmp_path, nom="temp_sonde_rapport.py"):
    logique = str(tmp_path / "demo" / "bouzecode" / nom)
    _write(logique, "print('ok')", temp=True)
    return logique, scratch.lookup_temp(logique)


@pytest.mark.parametrize("forme", [
    "uv run --no-sync python temp_sonde_rapport.py 2>&1 | Select-Object -First 120",
    "python .\\temp_sonde_rapport.py",
    "python ./temp_sonde_rapport.py",
    'python "temp_sonde_rapport.py"',
])
def test_le_nom_court_est_substitue(tmp_path, monkeypatch, forme):
    monkeypatch.chdir(tmp_path)
    _, reel = _temp(tmp_path)
    out = _substitute_scratch_paths(forme)
    assert reel in out
    assert "temp_sonde_rapport.py 2>&1" not in out or reel + " 2>&1" in out


def test_un_chemin_devine_inexistant_est_substitue(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _, reel = _temp(tmp_path, "temp_autopsie_session.py")
    devine = str(tmp_path / "Temp" / "bouzecode_scratch" / "b8ba29c6" / "temp_autopsie_session.py")
    out = _substitute_scratch_paths(f"uv run --no-sync python {devine}")
    assert out == f"uv run --no-sync python {reel}"


def test_un_vrai_fichier_du_meme_nom_gagne(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _temp(tmp_path)
    (tmp_path / "temp_sonde_rapport.py").write_text("vrai", encoding="utf-8")
    assert _substitute_scratch_paths("python temp_sonde_rapport.py") == "python temp_sonde_rapport.py"


def test_un_nom_ambigu_nest_pas_devine(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _temp(tmp_path)
    _write(str(tmp_path / "autre" / "temp_sonde_rapport.py"), "x", temp=True)
    assert _substitute_scratch_paths("python temp_sonde_rapport.py") == "python temp_sonde_rapport.py"


def test_un_mot_plus_long_nest_pas_touche(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _temp(tmp_path)
    cmd = "python temp_sonde_rapport.py.bak ; echo xtemp_sonde_rapport.py"
    assert _substitute_scratch_paths(cmd) == cmd
