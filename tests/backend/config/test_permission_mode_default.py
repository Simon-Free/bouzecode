import os
import subprocess
import sys


def _permission_mode_for_fresh_profile(home_dir) -> str:
    """Mode de permissions vu par un process bouzecode dont le profil (~/.bouzecode) est vierge."""
    env = {**os.environ, "USERPROFILE": str(home_dir), "HOME": str(home_dir)}
    code = "from bouzecode.backend.core.config import load_config; print(load_config()['permission_mode'])"
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                            text=True, timeout=30, check=True)
    return result.stdout.strip()


def test_fresh_install_never_asks_permission(tmp_path):
    """Un poste neuf (aucun config.json) tourne en accept-all : pas de question a chaque outil."""
    assert _permission_mode_for_fresh_profile(tmp_path) == "accept-all"


def test_saved_permission_mode_still_wins(tmp_path):
    """Un choix enregistre par /permissions reste prioritaire sur le defaut."""
    (tmp_path / ".bouzecode").mkdir()
    (tmp_path / ".bouzecode" / "config.json").write_text('{"permission_mode": "auto"}', encoding="utf-8")
    assert _permission_mode_for_fresh_profile(tmp_path) == "auto"
