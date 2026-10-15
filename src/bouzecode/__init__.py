# [desc] Package entry point exposing main(), VERSION, COMMANDS, and handle_slash via lazy imports ; sous pytest, isole le HOME avant tout chemin figé. [/desc]
"""bouzecode package."""
import os as _os
import sys as _sys


#  Sous pytest, le HOME est redirigé AVANT le premier chemin `~/.bouzecode` figé à l'import,
#  quelle que soit la ligne de commande : `-o addopts=""`, `--noconftest`, fichier de test hors
#  du dépôt (pas de conftest racine), `pytest.main()` d'un script. Deux fuites dans le vrai
#  profil le 2026-10-06 venaient de là. Déjà fait (plugin chargé, ou process enfant d'un test
#  qui hérite du HOME jetable) quand `BZ_TESTS_VRAI_HOME` est posé.
if "_pytest" in _sys.modules and not _os.environ.get("BZ_TESTS_VRAI_HOME"):
    import bouzecode.web_v2.tests.pytest_home_etanche  # noqa: F401,E402


def main():
    from .ui.cli import main as _main
    return _main()


def __getattr__(name):
    if name == "VERSION":
        from .ui.cli import VERSION
        return VERSION
    if name == "COMMANDS":
        from bouzecode.backend.commands.dispatcher import COMMANDS
        return COMMANDS
    if name == "handle_slash":
        from bouzecode.backend.commands.dispatcher import handle_slash
        return handle_slash
    if name in ("clr", "info", "ok", "warn", "err"):
        from . import ui as _ui_pkg  # noqa: F401  (ensure subpackage initialised)
        from .ui.ansi import clr, info, ok, warn, err
        return {"clr": clr, "info": info, "ok": ok, "warn": warn, "err": err}[name]
    raise AttributeError(f"module 'bouzecode' has no attribute {name!r}")
