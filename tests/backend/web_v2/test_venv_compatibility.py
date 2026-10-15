"""Un venv que uv jugerait invalide ne doit jamais lui etre DESIGNE.

Le 2026-08-24, `bouzecode/.venv/Lib/site-packages` a ete vide trois fois. A chaque
fois, tous les agents lances ensuite mouraient sur `ModuleNotFoundError: No module
named 'anthropic'`. La cause : `pyvenv.cfg` gravait `version_info = 3.12.12` alors
que son `home` pointait le lien ROULANT d'uv, repointe vers 3.12.13 le 2026-08-20.
uv en concluait que le venv etait invalide, le vidait, puis echouait a le recreer
(`Scripts/bouzecode.exe` verrouille par les agents CLI) sans reecrire
`pyvenv.cfg` — donc le `uv sync` suivant recommencait.

Ces tests fabriquent des `pyvenv.cfg` en tmpdir : ils n'installent rien, ne lancent
ni uv ni interpreteur, et ne peuvent donc pas reproduire le degat qu'ils decrivent.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from bouzecode.web_v2.runtime import venv_env  # noqa: E402


def _venv(racine: Path, home: str, version: str) -> str:
    """Un venv minimal mais credible : `pyvenv.cfg` + le dossier d'executables."""
    venv = racine / ".venv"
    (venv / ("Scripts" if venv_env.os.name == "nt" else "bin")).mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(
        f"home = {home}\nimplementation = CPython\nversion_info = {version}\n",
        encoding="utf-8",
    )
    return str(venv)


def test_un_venv_dont_la_version_a_decroche_est_incompatible(tmp_path):
    """Le cas exact du 2026-08-24 : grave 3.12.12, interpreteur 3.12.13."""
    interpreteur = tmp_path / "cpython-3.12.13-windows-x86_64-none"
    interpreteur.mkdir()
    venv = _venv(tmp_path / "projet", str(interpreteur), "3.12.12")

    assert venv_env.is_compatible(venv) is False


def test_un_venv_a_jour_est_compatible(tmp_path):
    interpreteur = tmp_path / "cpython-3.12.13-windows-x86_64-none"
    interpreteur.mkdir()
    venv = _venv(tmp_path / "projet", str(interpreteur), "3.12.13")

    assert venv_env.is_compatible(venv) is True


def test_le_suffixe_final_0_n_est_pas_un_ecart(tmp_path):
    """uv ecrit parfois `3.13.1.final.0` : c'est un format, pas une autre version."""
    interpreteur = tmp_path / "cpython-3.13.1-windows-x86_64-none"
    interpreteur.mkdir()
    venv = _venv(tmp_path / "projet", str(interpreteur), "3.13.1.final.0")

    assert venv_env.is_compatible(venv) is True


def test_une_version_indeterminable_ne_fait_pas_refuser(tmp_path):
    """`C:\\Program Files\\Python313` ne porte pas de version lisible dans son nom.

    On ne refuse pas un venv sain sur une supposition : sans les deux versions, la
    garde s'abstient."""
    interpreteur = tmp_path / "Python313"
    interpreteur.mkdir()
    venv = _venv(tmp_path / "projet", str(interpreteur), "3.13.1")

    assert venv_env.is_compatible(venv) is True


def test_un_venv_incompatible_reste_UTILISABLE_mais_n_est_plus_designe_a_uv(tmp_path):
    """La garde ne prive pas l'agent de son environnement : elle le cache a uv.

    `VIRTUAL_ENV` et `PATH` restent poses — l'agent execute normalement. Seul
    `UV_PROJECT_ENVIRONMENT` disparait, car c'est LUI qui dit a uv quoi detruire."""
    interpreteur = tmp_path / "cpython-3.12.13-windows-x86_64-none"
    interpreteur.mkdir()
    venv = _venv(tmp_path / "projet", str(interpreteur), "3.12.12")

    env = venv_env.base_venv_env(venv, environ={"PATH": "/usr/bin"})

    assert env["VIRTUAL_ENV"] == str(Path(venv))
    assert str(venv_env.venv_bin_dir(venv)) in env["PATH"]
    assert "UV_PROJECT_ENVIRONMENT" not in env


def test_un_venv_compatible_est_bien_designe_a_uv(tmp_path):
    interpreteur = tmp_path / "cpython-3.12.13-windows-x86_64-none"
    interpreteur.mkdir()
    venv = _venv(tmp_path / "projet", str(interpreteur), "3.12.13")

    env = venv_env.base_venv_env(venv, environ={"PATH": "/usr/bin"})

    assert env["UV_PROJECT_ENVIRONMENT"] == str(Path(venv))
