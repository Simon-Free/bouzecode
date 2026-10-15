# [desc] Progression en direct d'un outil de l'agent principal : dans la ligne vivante du spinner du TUI, sinon une ligne `\r` sur stderr (web, CLI non interactif). [/desc]
"""Ou s'affiche la progression (pytest n/N) d'un outil lance par l'agent PRINCIPAL.

Un sous-agent en process a son propre canal (`FicheAgent.progression`, imprimee dans son
onglet, cf. registration._progression_outil). Pour le principal :

- dans le TUI, le spinner tient deja une ligne vivante redessinee dix fois par seconde ;
  une barre ecrite a cote, sur stderr, etait ecrasee a chaque frame (effacee net quand la
  barre des sous-agents est dessinee, `\\r\\x1b[J`). La progression prend donc la place de
  la phrase du spinner : une seule ligne vivante, plus de conflit ;
- sans spinner (agent web, CLI non interactif) : une ligne `\\r` sur stderr, close par un
  saut de ligne a la fin du run.

Avant le 2026-10-05, c'etait une barre `tqdm` sur stderr ; `tqdm` n'etait qu'une dependance
transitive d'openai 2.x et a disparu du venv avec openai 3 : la barre ne s'affichait plus nulle
part, sans erreur (`ImportError` avale).
"""
from __future__ import annotations

import sys


class LigneProgression:
    """Callable(str) : affiche la progression ; `fermer()` termine la ligne stderr."""

    def __init__(self) -> None:
        self._sur_stderr = False

    def __call__(self, texte: str) -> None:
        from bouzecode.ui.spinner import afficher_progression
        if afficher_progression(texte):
            return
        sys.stderr.write(f"\r{texte}")
        sys.stderr.flush()
        self._sur_stderr = True

    def fermer(self) -> None:
        if self._sur_stderr:
            sys.stderr.write("\n")
            sys.stderr.flush()
