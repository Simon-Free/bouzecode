# [desc] AskUserQuestion dans un run non interactif (`-p`, ou sans console) ne bloque jamais : il rend la consigne « décide, note l'hypothèse, signale-la ». [/desc]
"""Session 9d81964e (2026-10-06) : « No Windows console found » chez le parent `-p`, et deux
enfants `-p` bloqués des heures sur une saisie dans un onglet de terminal."""
from __future__ import annotations

import os
import subprocess
import sys

from bouzecode.backend.tools.interaction import (
    REPONSE_SANS_HUMAIN, _ask_user_question, personne_pour_repondre,
)


def test_run_non_interactif_rend_la_consigne_sans_attendre():
    reponse = _ask_user_question("Staging ou prod ?", [{"label": "staging"}],
                                 config={"_non_interactif": True})
    assert reponse == REPONSE_SANS_HUMAIN
    assert "Methodology" in reponse and "FinalAnswer" in reponse


def test_mode_p_compte_comme_non_interactif_meme_avec_une_console():
    assert personne_pour_repondre({"_non_interactif": True})


def test_vrai_sous_process_sans_console_ne_bloque_pas():
    """stdin fermé (aucune console) : la question rend la main au lieu d'attendre."""
    script = ("from bouzecode.backend.tools.interaction import _ask_user_question; "
              "print(_ask_user_question('Q ?', None, True, config={})[:30])")
    sortie = subprocess.run([sys.executable, "-c", script], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, encoding="utf-8", timeout=60,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=True).stdout
    assert sortie.strip() == REPONSE_SANS_HUMAIN[:30]
