"""Intégration sérialisée ENTRE process : un sous-agent intègre depuis son propre process, le
verrou par thread ne le voyait pas. Vrai git, vrai second process."""
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from bouzecode.web_v2.services.work import worktrees


def _depot(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    return repo


def test_un_autre_process_attend_la_fin_de_l_integration_en_cours(tmp_path):
    repo = _depot(tmp_path)
    temoin = tmp_path / "temoin"
    pret = tmp_path / "pret"
    lache = tmp_path / "lache"
    code = textwrap.dedent(f"""
        import pathlib, time
        from bouzecode.web_v2.services.work import worktrees
        with worktrees.verrou_inter_process({str(repo)!r}, "main"):
            pathlib.Path({str(pret)!r}).write_text("1")
            fin = time.monotonic() + 30
            while not pathlib.Path({str(lache)!r}).exists() and time.monotonic() < fin:
                time.sleep(0.02)
            pathlib.Path({str(temoin)!r}).write_text("fini")
    """)
    src = str(Path(worktrees.__file__).resolve().parents[4])
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([src, os.environ.get("PYTHONPATH", "")])}
    enfant = subprocess.Popen([sys.executable, "-c", code], env=env)
    try:
        fin = time.monotonic() + 30
        while not pret.exists() and enfant.poll() is None and time.monotonic() < fin:
            time.sleep(0.02)  # attente bornée de l'état « verrou pris par l'enfant »
        assert pret.exists()
        # Tenu par l'autre process : pas obtenu sans attendre.
        with worktrees.verrou_inter_process(str(repo), "main", delai_s=0):
            assert not temoin.exists()  # délai 0 : on a continué SANS verrou (journalisé)
        lache.write_text("1")
        with worktrees.verrou_inter_process(str(repo), "main"):
            assert temoin.read_text() == "fini"  # obtenu seulement après sa libération
    finally:
        lache.write_text("1")
        enfant.wait(30)


def test_verrou_libre_obtenu_aussitot_et_reutilisable(tmp_path):
    repo = _depot(tmp_path)
    for _ in range(3):
        with worktrees.verrou_inter_process(str(repo), "feature/x"):
            pass
    assert (repo / ".git" / "bouzecode-integrate-feature_x.lock").exists()


def test_hors_depot_git_pas_de_verrou(tmp_path):
    with worktrees.verrou_inter_process(str(tmp_path), "main"):
        pass
