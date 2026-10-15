"""Le REPL doit annoncer son etat dans le titre du terminal DES le demarrage.

Sans titre pose au demarrage, VSCode (dont l'onglet suit `${sequence}`) n'a aucune
sequence OSC a afficher et retombe sur le nom du processus (« TCLauncherHelper »).

Pilote minimal : `_read_input` (src/bouzecode/ui/repl.py L910-914) appelle `input(prompt)`
des que `sys.stdin.isatty()` est faux -> pas besoin de prompt_toolkit.
"""
import contextlib
import sys
import threading

from bouzecode.ui import terminal_title


def _repl_jusqua_exit(monkeypatch, dossier):
    """Lance repl() avec un clavier qui tape /exit, et rend les statuts poses."""
    from bouzecode.backend.core import config as module_config
    from bouzecode.backend.core import tool_registry
    from bouzecode.backend.core.config import load_config
    from bouzecode.ui import rendering
    from bouzecode.ui.barre_agents import rendu
    from bouzecode.ui.repl import repl

    # Globaux de rendu que repl() fixe : restaures pour les tests suivants du worker.
    monkeypatch.setattr(rendering, "_RICH_LIVE", rendering._RICH_LIVE)
    monkeypatch.setattr(rendu, "_source_pied", None)
    monkeypatch.setattr(rendu, "_pied_dessine", False)
    monkeypatch.setattr(tool_registry, "_flotte_locale", False)
    # Sessions et journaux dans le dossier du test.
    monkeypatch.setattr(module_config, "DAILY_DIR", dossier / "daily")
    monkeypatch.setattr(module_config, "CONFIG_DIR", dossier)

    poses: list[str] = []
    monkeypatch.setattr(terminal_title, "set_terminal_status",
                        lambda status, stream=None: poses.append(status) or True)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "/exit")

    config = load_config()
    config.update(permission_mode="accept-all", rich_live=False)

    def lancer():
        with contextlib.suppress(SystemExit):
            repl(config)

    fil = threading.Thread(target=lancer, daemon=True)
    fil.start()
    fil.join(60)
    assert not fil.is_alive(), "le REPL n'a pas quitte sur /exit"
    return poses


def test_le_repl_annonce_son_etat_au_terminal_au_demarrage(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    poses = _repl_jusqua_exit(monkeypatch, tmp_path)

    assert poses, "le REPL n'a pose aucun statut dans le titre du terminal"
    assert poses[0] == "idle", f"premier statut inattendu : {poses!r}"
