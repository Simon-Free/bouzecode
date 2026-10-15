# [desc] `--enable-chrome-devtools` seul (sans variable d'environnement) enregistre les outils mcp__chrome-devtools__* depuis le manifeste, dans un vrai sous-process. [/desc]
"""Session 9d81964e (2026-10-06) : le pré-scan de sys.argv venait APRÈS les imports qui
enregistrent les outils ; le parent lancé avec le drapeau n'avait aucun outil navigateur."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_MANIFESTE = {"tools": [
    {"name": "navigate_page", "description": "Navigate", "inputSchema": {"type": "object"}},
    {"name": "take_snapshot", "description": "Snapshot", "inputSchema": {"type": "object"}},
]}

_COMPTE = ("from bouzecode.backend.core.tool_registry import get_tool_schemas; "
           "print(sum(s['name'].startswith('mcp__chrome-devtools__') for s in get_tool_schemas()))")


def _lancer(tmp_path: Path, script: str) -> int:
    """Sous-process au HOME isolé (manifeste à 2 outils), sans la variable d'environnement."""
    (tmp_path / ".bouzecode").mkdir(exist_ok=True)
    (tmp_path / ".bouzecode" / "chrome_devtools_manifest.json").write_text(
        json.dumps(_MANIFESTE), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "BOUZECODE_ENABLE_CHROME_DEVTOOLS"}
    env.update(USERPROFILE=str(tmp_path), HOME=str(tmp_path))
    sortie = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=120, check=True).stdout
    return int(sortie.strip().splitlines()[-1])


def test_drapeau_seul_a_l_import_de_la_cli(tmp_path):
    script = ("import sys; sys.argv = ['bouzecode', '-p', '--enable-chrome-devtools', 'x']; "
              "import bouzecode.ui.cli; " + _COMPTE)
    assert _lancer(tmp_path, script) == 2


def test_sans_drapeau_aucun_outil_navigateur(tmp_path):
    script = "import sys; sys.argv = ['bouzecode', '-p', 'x']; import bouzecode.ui.cli; " + _COMPTE
    assert _lancer(tmp_path, script) == 0


def test_outils_deja_enregistres_avant_la_cli_rattrapes_au_parsing(tmp_path):
    script = ("import bouzecode.backend.tools; "
              "from bouzecode.ui.cli import build_parser, activer_chrome_devtools_si_demande; "
              "activer_chrome_devtools_si_demande("
              "build_parser().parse_args(['-p', '--enable-chrome-devtools', 'x'])); " + _COMPTE)
    assert _lancer(tmp_path, script) == 2
