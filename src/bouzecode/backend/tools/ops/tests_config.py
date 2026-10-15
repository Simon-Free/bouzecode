# [desc] Lecture de `.bouzecode/tests.yaml`, clé `impacted` (always, map, slow) ; globs `**` façon pathlib, aussi dans `tests` et `always` ; les autres clés (browser, app_server) sont ignorées. [/desc]
"""Configuration de la sélection impactée d'un projet : `<projet>/.bouzecode/tests.yaml`.

    impacted:
      always: [tests/security, tests/test_shared_settings.py]   # contrôles transverses bon marché
      map:                                                      # ce que testmon ne voit pas
        - paths: ["src/apps/formation_continue/**", "src/vendor/**"]
          tests: ["tests/formation", "tests/browser/test_demoapp_tutorial_*.py"]
      slow: ["tests/test_interaction_fields.py"]                # hors run sauf full=true ou cible

Globs : `**` traverse les dossiers (zéro ou plus), `*` et `?` non. Absent : config vide.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CHEMIN_CONFIG = Path(".bouzecode") / "tests.yaml"
_DOSSIERS_IGNORES = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}


@dataclass(frozen=True)
class RegleMap:
    paths: tuple[str, ...]
    tests: tuple[str, ...]


@dataclass(frozen=True)
class ConfigTests:
    always: tuple[str, ...] = ()
    map: tuple[RegleMap, ...] = ()
    slow: tuple[str, ...] = ()

    def tests_pour(self, chemin: str) -> list[str]:
        """Motifs de tests des règles `map` dont un motif `paths` couvre `chemin`."""
        return [t for regle in self.map if any(correspond(p, chemin) for p in regle.paths)
                for t in regle.tests]


@lru_cache(maxsize=512)
def _regex(motif: str) -> re.Pattern:
    morceaux, i = [], 0
    while i < len(motif):
        if motif.startswith("**/", i):
            morceaux.append("(?:.*/)?")
            i += 3
        elif motif.startswith("**", i):
            morceaux.append(".*")
            i += 2
        else:
            c = motif[i]
            morceaux.append("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c))
            i += 1
    return re.compile("".join(morceaux) + r"\Z")


def correspond(motif: str, chemin: str) -> bool:
    return bool(_regex(motif.strip("/")).match(chemin.replace("\\", "/")))


def etendre(racine: Path, motif: str) -> list[str]:
    """Chemins existants (relatifs, posix) désignés par `motif` ; sans joker : lui-même s'il existe."""
    if not any(c in motif for c in "*?"):
        return [motif] if (racine / motif).exists() else []
    fixe = re.split(r"[*?]", motif, maxsplit=1)[0].rsplit("/", 1)[0] if "/" in motif else ""
    trouves = []
    for dossier, sous_dossiers, fichiers in os.walk(racine / fixe):
        sous_dossiers[:] = [d for d in sous_dossiers if d not in _DOSSIERS_IGNORES]
        relatif = Path(dossier).relative_to(racine).as_posix()
        for nom in sous_dossiers + fichiers:
            chemin = f"{relatif}/{nom}" if relatif != "." else nom
            if correspond(motif, chemin):
                trouves.append(chemin)
    return sorted(trouves)


def _liste(valeur, cle: str) -> tuple[str, ...]:
    if valeur is None:
        return ()
    if not isinstance(valeur, list) or not all(isinstance(v, str) for v in valeur):
        raise ValueError(f"{CHEMIN_CONFIG} : `impacted.{cle}` doit être une liste de chemins.")
    return tuple(valeur)


def lire_config_tests(racine: Path) -> ConfigTests:
    fichier = racine / CHEMIN_CONFIG
    if not fichier.is_file():
        return ConfigTests()
    import yaml
    brut = (yaml.safe_load(fichier.read_text(encoding="utf-8")) or {}).get("impacted") or {}
    regles = []
    for numero, regle in enumerate(brut.get("map") or []):
        if not isinstance(regle, dict):
            raise ValueError(f"{CHEMIN_CONFIG} : `impacted.map[{numero}]` doit porter paths et tests.")
        regles.append(RegleMap(_liste(regle.get("paths"), f"map[{numero}].paths"),
                               _liste(regle.get("tests"), f"map[{numero}].tests")))
    return ConfigTests(always=_liste(brut.get("always"), "always"), map=tuple(regles),
                       slow=_liste(brut.get("slow"), "slow"))
