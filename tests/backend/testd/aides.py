# [desc] Aides des tests testd : projet pytest jetable, commande pytest [/desc]
from __future__ import annotations

import sys
import textwrap
from pathlib import Path


def projet(racine: Path, fichiers: dict[str, str]) -> Path:
    """Petit projet pytest jetable."""
    racine.mkdir(parents=True, exist_ok=True)
    (racine / "pyproject.toml").write_text("[project]\nname='jetable'\nversion='0'\n", encoding="utf-8")
    for nom, contenu in fichiers.items():
        (racine / nom).write_text(textwrap.dedent(contenu), encoding="utf-8")
    return racine


def commande(*cibles: str, workers: int = 0) -> list[str]:
    """`python -m pytest -v <cibles>` avec le python de ce run (pytest + xdist présents)."""
    return [sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider",
            *(["-n", str(workers)] if workers else []), *cibles]
