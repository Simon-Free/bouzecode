# [desc] RunPythonTest guard rails: capped xdist parallelism, --durations, faulthandler_timeout=120 and no rerun by default, `show` views validated [/desc]
"""What RunPythonTest refuses, and what it adds, before pytest is built.

Constat du 2026-09-29 : un agent lancé sur la suite a pris `-n auto` (20 workers) dès son
premier run, parce que c'était le DÉFAUT de l'outil, et la description l'invitait à tout
lancer (« Sans cible : toute la suite »). La machine est partagée : `-n auto` a déjà
saturé la mémoire et fait tuer le serveur web_v2 et d'autres agents. Les règles vivent
donc dans l'outil, pas seulement dans un CLAUDE.md que le modèle ne lit pas toujours.
"""
from __future__ import annotations

import os

DEFAULT_PARALLEL = "4"
DEFAULT_DURATIONS = "--durations=5"
DETAILED_DURATIONS = "--durations=15"

_UNBOUNDED_WORKERS = ("auto", "logical")
_GLUED_UNBOUNDED_FLAGS = {f"{flag}{workers}" for flag in ("-n", "-n=", "--numprocesses=")
                          for workers in _UNBOUNDED_WORKERS}


def xdist_args(parallel: str, extra_args: list[str] | None = None) -> tuple[list[str], str]:
    """`-n` arguments for `parallel`, or an error saying why it is refused.

    `extra_args` is checked too: `-n auto` must not come back through the side door."""
    value = str(parallel).strip().lower()
    if value in _UNBOUNDED_WORKERS or _unbounded_workers_in(extra_args):
        return [], (
            "Error: `-n auto` refusé (parallel='auto' ou extra_args) : un worker par cœur "
            "(20 ici), sur une machine partagée avec d'autres agents — ça a déjà saturé la "
            "mémoire et fait tuer le serveur. Utilise parallel='4' (défaut), '2', ou 'off'."
        )
    if value == "off":
        return [], ""
    if not value.isdigit() or int(value) < 1:
        return [], (
            f"Error: parallel={parallel!r} invalide : attendu un nombre de workers "
            "('4' par défaut, '2') ou 'off'."
        )
    return ["-n", value], ""


def _unbounded_workers_in(extra_args: list[str] | None) -> bool:
    """True when `extra_args` smuggles an unbounded `-n auto` past `parallel`."""
    args = [str(a).strip().lower() for a in extra_args or []]
    for arg, following in zip(args, args[1:] + [""]):
        if arg in ("-n", "--numprocesses") and following in _UNBOUNDED_WORKERS:
            return True
        if arg in _GLUED_UNBOUNDED_FLAGS:
            return True
    return False



def full_suite_refusal(full: bool) -> str:
    """`full=True` réservé au build nightly (`BZ_NIGHTLY=1`), décision du 2026-10-14 : un agent
    ne lance que les tests impactés ; la suite complète tourne la nuit sur develop et alimente
    la comparaison avec la base."""
    if not full or os.environ.get("BZ_NIGHTLY") == "1":
        return ""
    return ("Error: full=true refusé. La suite complète tourne en nightly sur develop ; "
            "lance les tests impactés (sans `targets`).")


def caller_chose_durations(extra_args: list[str] | None) -> bool:
    return any(str(a).startswith("--durations") and not str(a).startswith("--durations-min")
               for a in extra_args or [])


def with_default_durations(extra_args: list[str] | None, show=()) -> list[str]:
    """`extra_args` plus a `--durations`, unless the caller already chose one.

    `--durations=5` by default: the result only shows the slowest tests above 1 s anyway;
    `show=['durations']` asks for the 15 slowest."""
    args = list(extra_args or [])
    if caller_chose_durations(args):
        return args
    return args + [DETAILED_DURATIONS if "durations" in show else DEFAULT_DURATIONS]


def with_safe_defaults(extra_args: list[str] | None) -> list[str]:
    """`extra_args` plus le diagnostic des tests figés et sans rejeu, sauf choix de l'appelant.

    Suite finale du 2026-10-13 : 50 min sans rien voir d'un worker bloqué (aucune pile), et
    pytest-rerunfailures rejouait chaque échec (166 rejeux). `faulthandler_timeout=120` vide
    la pile d'un test bloqué depuis 2 min ; `-p no:rerunfailures` coupe le rejeu (sans effet
    si le plugin n'est pas installé)."""
    args = list(extra_args or [])
    if not any("faulthandler_timeout" in str(a) for a in args):
        args += ["-o", "faulthandler_timeout=120"]
    if not any(str(a).startswith("--reruns") for a in args):
        args += ["-p", "no:rerunfailures"]
    return args


def show_views(show) -> tuple[tuple[str, ...], str]:
    """`show` (str or list) as a tuple of known views, or an error naming the valid ones."""
    from .pytest_compact import VUES
    views = (show,) if isinstance(show, str) else tuple(show or ())
    views = tuple(str(v).strip().lower() for v in views if str(v).strip())
    unknown = [v for v in views if v not in VUES]
    if unknown:
        return (), f"Error: show={unknown!r} inconnu ; valeurs possibles : {list(VUES)}."
    return views, ""
