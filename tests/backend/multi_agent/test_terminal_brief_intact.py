# [desc] Le brief d'un sous-agent en terminal arrive intact (`;`, guillemets, retours ligne) : il voyage par --prompt-file, options avant. [/desc]
"""Incident du 2026-10-06 : `wt.exe` coupait la ligne de commande au premier `;` du brief.
Les enfants recevaient 57 % et 15 % de leur brief, sans `--result-file` ni `--accept-all`."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from bouzecode.backend.multi_agent.terminal import build_terminal_command, prompt_file_path
from bouzecode.ui.cli import build_parser, prompt_initial

BRIEF = ('STAGING_URL="https://staging.corps3.demoapp.com" câblé ; authenticate(account)\n'
         "## Objectif\nfais un grep pour le vérifier ; admin_api l'utilise « peut-être »\n"
         'fin "guillemets" ; C:\\dossier\\ antislash final\\')


def _argv_de_l_enfant(commande: list[str]) -> list[str]:
    """Les arguments de bouzecode dans la commande wt (après `-- python -m bouzecode`)."""
    debut = commande.index("--") + 1
    return commande[debut + 3:]


def test_wt_ne_recoit_ni_le_brief_ni_ses_caracteres_speciaux(tmp_path):
    commande = build_terminal_command(BRIEF, str(tmp_path / "r.result.txt"), {"model": "m"},
                                      terminal_app="wt")
    assert not any(";" in arg or "\n" in arg or '"' in arg for arg in commande)


def test_les_options_precedent_le_prompt(tmp_path):
    argv = _argv_de_l_enfant(build_terminal_command(
        BRIEF, str(tmp_path / "r.result.txt"), {"model": "m"}, terminal_app="wt"))
    position_prompt = argv.index("--prompt-file")
    for option in ("--result-file", "--accept-all", "--model"):
        assert argv.index(option) < position_prompt


def test_le_brief_relu_par_l_enfant_est_identique(tmp_path):
    result_file = str(tmp_path / "r.result.txt")
    Path(prompt_file_path(result_file)).write_text(BRIEF, encoding="utf-8")
    argv = _argv_de_l_enfant(build_terminal_command(BRIEF, result_file, {}, terminal_app="wt"))
    assert prompt_initial(build_parser().parse_args(argv)) == BRIEF


def test_vrai_sous_process_relit_le_brief_intact(tmp_path):
    """Les arguments passent par CreateProcess comme pour l'enfant ; il relit le fichier."""
    result_file = str(tmp_path / "r.result.txt")
    Path(prompt_file_path(result_file)).write_text(BRIEF, encoding="utf-8")
    argv = _argv_de_l_enfant(build_terminal_command(BRIEF, result_file, {}, terminal_app="wt"))
    sortie = tmp_path / "relu.txt"
    script = ("import sys; from pathlib import Path; "
              "from bouzecode.ui.cli import build_parser, prompt_initial; "
              "Path(sys.argv[1]).write_text(prompt_initial(build_parser().parse_args(sys.argv[2:])),"
              " encoding='utf-8')")
    subprocess.run([sys.executable, "-c", script, str(sortie), *argv], check=True, timeout=60)
    assert sortie.read_text(encoding="utf-8") == BRIEF
