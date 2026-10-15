# [desc] Le spawn d'agent doit résister au shadowing du package bouzecode par le cwd
# (ex. projet bouzecode_oss avec un bouzecode.py à la racine). [/desc]
import os
import subprocess
from pathlib import Path

from bouzecode.web_v2.runtime.runner import agent_commande


def test_launch_cmd_uses_safe_path():
    cmd = agent_commande._bouzecode_launch_cmd()
    assert "-P" in cmd, "sans -P, un bouzecode.py dans le cwd du projet shadow le package"


def test_spawn_env_prepends_server_package_root(monkeypatch, tmp_path):
    # Chemin de la plateforme : un littéral « C:\\… » contient le séparateur « : » de POSIX.
    ailleurs = str(tmp_path / "ailleurs")
    monkeypatch.setenv("PYTHONPATH", ailleurs)
    env = agent_commande._spawn_env()
    parts = env["PYTHONPATH"].split(os.pathsep)
    import bouzecode

    # pkg_root (src/) always wins first so bouzecode is never shadowed.
    assert Path(parts[0]) == Path(bouzecode.__file__).resolve().parents[1]
    # The previous PYTHONPATH entry survives, at the end.
    assert parts[-1] == ailleurs
    assert env["PYTHONUNBUFFERED"] == "1"


def test_server_bouzecode_dir_points_at_a_real_directory():
    """`--extra-dir` doit désigner un `.bouzecode/` QUI EXISTE, sinon les profils
    transversaux (monitor/review/manager) ne se résolvent pas et l'agent retombe en
    silence sur le profil par défaut.

    Ce test et les deux voisins tiennent la MÊME règle : les trois chemins de `runner.py`
    sont calculés en `parents[N]` depuis l'emplacement du fichier. Le déplacement de
    `web_v2/runner.py` vers `web_v2/runtime/runner.py` les a tous décalés d'un cran sans
    que rien ne le signale — seul le PYTHONPATH avait un test, les deux autres non."""
    extra_dir = agent_commande._server_bouzecode_dir()
    assert extra_dir.name == ".bouzecode"
    assert extra_dir.is_dir(), (
        f"{extra_dir} n'existe pas — l'--extra-dir passé au spawn ne désigne rien")


def test_spawn_env_keeps_extra_vars():
    """Ce que le test tient, c'est le PASSE-PLAT : _spawn_env laisse traverser les
    variables qu'on lui donne. L'exemple servait auparavant à illustrer avec
    BOUZECODE_PARALYSIS_ABORT_AFTER, retiré le 2026-07-29 faute de lecteur."""
    env = agent_commande._spawn_env(BOUZECODE_WEB_IPC_DIR="/agents/x.ipc")
    assert env["BOUZECODE_WEB_IPC_DIR"] == "/agents/x.ipc"


def test_module_resolution_ignores_cwd_decoy(tmp_path):
    (tmp_path / "bouzecode.py").write_text("import sys; sys.exit('decoy importe')\n")
    cmd = [*agent_commande._bouzecode_launch_cmd(), "--version"]
    result = subprocess.run(
        cmd, cwd=tmp_path, env=agent_commande._spawn_env(),
        capture_output=True, text=True, timeout=60,
    )
    output = result.stdout + result.stderr
    assert "decoy" not in output
    assert result.returncode == 0, output
