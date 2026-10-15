# [desc] Dossier de travail et variables d'environnement PROPRES a l'agent qui execute l'outil courant (contextvar) : un sous-agent en process isole dans son worktree sans os.chdir global. [/desc]
"""Plusieurs agents vivent dans le meme process (sous-agents du TUI) : `os.chdir` et
`os.environ` sont partages, un worktree « adopte » par l'un deplacerait tous les autres.

Un agent isole porte un `Atelier` (son dossier + ses variables) dans sa config
(`config["_atelier"]`). `tool_registry.execute_tool` l'active pour la duree de chaque appel
d'outil (contextvar : propre au fil, donc aux outils lances en parallele), et les outils lisent
le dossier courant par `courant()`, resolvent les chemins relatifs par `absolu()` et forment
l'env de leurs process par `environ()`. Sans atelier actif, tout retombe sur le process :
le comportement d'un agent seul dans son process est inchange.
"""
from __future__ import annotations

import contextlib
import contextvars
import os
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Atelier:
    dossier: str
    variables: dict = field(default_factory=dict)
    #  Ce que l'agent ecrit sur stdout/stderr (print, avertissements) : SON journal, pas le
    #  terminal du principal (core/sortie_agent.py). None : le flux du process.
    sortie: Any = None
    #  Sources de skills / projets charges PAR CET agent (LoadProjectConfig) : propres a lui,
    #  sinon le worktree d'un frere devient une source de skills pour tous (core/paths.py).
    dossiers_extra: list = field(default_factory=list)
    projets: list = field(default_factory=list)
    #  Callable sans argument, vrai quand l'agent est interrompu (Ctrl+C / x dans la barre) :
    #  les outils longs (Bash) le sondent pour tuer leur process au lieu de bloquer l'agent.
    annule: Any = None


_ATELIER: contextvars.ContextVar[Optional[Atelier]] = contextvars.ContextVar(
    "atelier_agent", default=None)


def actif() -> Optional[Atelier]:
    return _ATELIER.get()


@contextlib.contextmanager
def dans(atelier: Optional[Atelier]):
    """Active `atelier` pour le fil courant (None : rien ne change)."""
    if atelier is None:
        yield
        return
    jeton = _ATELIER.set(atelier)
    try:
        yield
    finally:
        _ATELIER.reset(jeton)


def courant() -> str:
    atelier = _ATELIER.get()
    return atelier.dossier if atelier is not None else os.getcwd()


def absolu(chemin) -> str:
    """Un chemin relatif se lit depuis le dossier de l'agent (pas celui du process)."""
    brut = os.path.expanduser(str(chemin))
    return brut if os.path.isabs(brut) else os.path.join(courant(), brut)


def resoudre(chemin):
    """`absolu` pour un agent a atelier ; le chemin tel quel sinon (sorties inchangees)."""
    return absolu(chemin) if _ATELIER.get() is not None and chemin else chemin


def variable(nom: str, defaut: str = "") -> str:
    atelier = _ATELIER.get()
    if atelier is not None and nom in atelier.variables:
        return atelier.variables[nom]
    return os.environ.get(nom, defaut)


def environ() -> dict[str, str]:
    """Copie de l'env du process + les variables de l'agent (venv dedie, worktree)."""
    env = os.environ.copy()
    atelier = _ATELIER.get()
    if atelier is not None:
        env.update(atelier.variables)
    return env


def deplacer(chemin: str, variables: Optional[dict] = None) -> bool:
    """Deplace l'AGENT (pas le process) ; False s'il n'a pas d'atelier (l'appelant fait alors
    son `os.chdir` / `os.environ` habituels)."""
    atelier = _ATELIER.get()
    if atelier is None:
        return False
    atelier.dossier = chemin
    atelier.variables.update(variables or {})
    return True


RACINE_WORKTREE = "BOUZECODE_WORKTREE_ROOT"


def aller(chemin: str) -> None:
    """Change le dossier de l'agent : son atelier s'il en a un, sinon le process."""
    if not deplacer(chemin):
        os.chdir(chemin)


def poser_variables(valeurs: dict) -> None:
    atelier = _ATELIER.get()
    if atelier is not None:
        atelier.variables.update(valeurs)
    else:
        os.environ.update(valeurs)


def poser_racine(chemin: str) -> None:
    """Pose (ou efface, avec "") la racine du worktree dedie de l'agent."""
    atelier = _ATELIER.get()
    if atelier is not None:
        atelier.variables[RACINE_WORKTREE] = chemin
    elif chemin:
        os.environ[RACINE_WORKTREE] = chemin
    else:
        os.environ.pop(RACINE_WORKTREE, None)
