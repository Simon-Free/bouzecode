# [desc] Le spawn d'agent doit résister au shadowing du package bouzecode par le cwd
# (ex. projet bouzecode_oss avec un bouzecode.py à la racine). [/desc]
import os
import subprocess
from pathlib import Path

from bouzecode.web_v2.runtime import runner


def test_launch_cmd_uses_safe_path():
    cmd = runner._bouzecode_launch_cmd()
    assert "-P" in cmd, "sans -P, un bouzecode.py dans le cwd du projet shadow le package"


def test_spawn_env_prepends_server_package_root(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", r"C:\ailleurs")
    env = runner._spawn_env()
    parts = env["PYTHONPATH"].split(os.pathsep)
    import bouzecode

    # pkg_root (src/) always wins first so bouzecode is never shadowed.
    assert Path(parts[0]) == Path(bouzecode.__file__).resolve().parents[1]
    # The previous PYTHONPATH entry survives, at the end (after any extra roots).
    assert parts[-1] == r"C:\ailleurs"
    assert env["PYTHONUNBUFFERED"] == "1"


def test_spawn_env_makes_readme_sync_importable_under_safe_path():
    # readme_sync is import-dead in spawned agents unless _spawn_env exposes the
    # repo root: -P drops the cwd from sys.path, and PYTHONPATH previously carried
    # only src/. This reproduces the exact spawn conditions and proves the package
    # resolves. Fails before the fix (find_spec None), passes after.
    # parents[4] depuis src/bouzecode/web_v2/runtime/runner.py. Avec parents[3] (valeur
    # d'avant le déplacement dans runtime/) ce chemin désignait `src/`, readme_sync n'y
    # était jamais trouvé et le test se SKIPPAIT au lieu d'échouer — la couverture avait
    # disparu en silence.
    repo_root = Path(runner.__file__).resolve().parents[4]
    if not (repo_root / "readme_sync" / "__init__.py").exists():
        import pytest

        pytest.skip("readme_sync not present at repo root in this checkout")
    probe = (
        "import importlib.util, sys; "
        "sys.exit(0 if importlib.util.find_spec('readme_sync') else 1)"
    )
    result = subprocess.run(
        [*runner._bouzecode_launch_cmd()[:2], "-c", probe],
        cwd=repo_root, env=runner._spawn_env(),
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        "readme_sync must be importable under the spawn env (-P + PYTHONPATH); "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_server_bouzecode_dir_points_at_a_real_directory():
    """`--extra-dir` doit désigner un `.bouzecode/` QUI EXISTE, sinon les profils
    transversaux (monitor/review/manager) ne se résolvent pas et l'agent retombe en
    silence sur le profil par défaut.

    Ce test et les deux voisins tiennent la MÊME règle : les trois chemins de `runner.py`
    sont calculés en `parents[N]` depuis l'emplacement du fichier. Le déplacement de
    `web_v2/runner.py` vers `web_v2/runtime/runner.py` les a tous décalés d'un cran sans
    que rien ne le signale — seul le PYTHONPATH avait un test, les deux autres non."""
    extra_dir = runner._server_bouzecode_dir()
    assert extra_dir.name == ".bouzecode"
    assert extra_dir.is_dir(), (
        f"{extra_dir} n'existe pas — l'--extra-dir passé au spawn ne désigne rien")


def test_spawn_env_keeps_extra_vars():
    """Ce que le test tient, c'est le PASSE-PLAT : _spawn_env laisse traverser les
    variables qu'on lui donne. L'exemple servait auparavant à illustrer avec
    BOUZECODE_PARALYSIS_ABORT_AFTER, retiré le 2026-07-29 faute de lecteur."""
    env = runner._spawn_env(BOUZECODE_WEB_IPC_DIR="/agents/x.ipc")
    assert env["BOUZECODE_WEB_IPC_DIR"] == "/agents/x.ipc"


def test_module_resolution_ignores_cwd_decoy(tmp_path):
    (tmp_path / "bouzecode.py").write_text("import sys; sys.exit('decoy importe')\n")
    cmd = [*runner._bouzecode_launch_cmd(), "--version"]
    result = subprocess.run(
        cmd, cwd=tmp_path, env=runner._spawn_env(),
        capture_output=True, text=True, timeout=60,
    )
    output = result.stdout + result.stderr
    assert "decoy" not in output
    assert result.returncode == 0, output
