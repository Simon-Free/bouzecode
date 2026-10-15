# [desc] Options qui rendent un pytest IMBRIQUÉ étanche : rootdir, basetemp et cache dans le tmp du test appelant. [/desc]
"""Un pytest lancé PAR un test ne doit voir que le dossier temporaire de ce test.

Sans rootdir à lui, un pytest dont la cible vit dans `%TEMP%` (fichier écrit dans `tmp_path`)
prend le dépôt pour rootdir : la cible est alors HORS de son `confcutdir`, et pytest collecte
chaque dossier parent de la cible — `%TEMP%` compris, qu'il parcourt entrée par entrée. Les
dossiers que les AUTRES pytest y créent et suppriment à ce moment (`bz-home-*`, `pytest-of-*`)
le font échouer « à la collecte » sur un `FileNotFoundError` qui n'a rien à voir avec le test.
Mesuré le 2026-10-05 : 1 à 5 rouges par run en `-n 4`, et 8 à 19 s par test, même en série, à
lister `%TEMP%`.

Sans basetemp à lui, il crée `pytest-of-<user>/pytest-N` à côté des autres sessions et purge
les plus anciens ; sans `-p no:cacheprovider`, il écrit `.pytest_cache` dans son rootdir.
"""
from __future__ import annotations

from pathlib import Path


def options_etanches(dossier: Path) -> list[str]:
    """basetemp et cache du pytest imbriqué dans `dossier` (le tmp du test appelant).

    Le rootdir, lui, se donne par le cwd : un pytest lancé DANS `dossier` sur une cible qui
    s'y trouve (sans inifile au-dessus) prend `dossier` pour rootdir et `confcutdir`, et une
    cible du dépôt garde le pyproject du dépôt — un `--rootdir` imposé la ferait échouer.
    Le basetemp est un dossier POINTÉ : `norecursedirs` l'ignore si la collecte passe dessus.
    """
    return ["--basetemp", (dossier / ".basetemp_imbrique").as_posix(), "-p", "no:cacheprovider"]
