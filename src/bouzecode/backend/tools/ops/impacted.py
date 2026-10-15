# [desc] Sélection impactée, défaut de RunPythonTest sans cible : fichiers changés par la branche → tests via testmon (Python), `.bouzecode/tests.yaml` (map, always, slow) et fichiers de test modifiés eux-mêmes ; une ligne dit quoi et pourquoi. [/desc]
"""`RunPythonTest()` sans cible lance ce que la branche peut avoir cassé, et rien d'autre.

- Fichiers changés : `git diff <merge-base develop|master>...HEAD` + non commités + non suivis.
- Python : la base testmon (`.testmondata` du projet, sinon celle du dépôt principal quand on
  est dans un worktree) donne les tests qui ont exécuté ce fichier. Lue en SQLite, sans relancer
  testmon : pas de surcoût de couverture. Absente : repli sur le mapping, et c'est dit.
- Le reste (templates, js, css, json, vendored) : `impacted.map` de `.bouzecode/tests.yaml`.
- Un fichier de test modifié se relance lui-même ; `always` à chaque fois ; `slow` écarté.
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .git_base import base_de_la_branche, fichiers_changes, git
from .tests_config import etendre, lire_config_tests


@dataclass
class Selection:
    ligne: str
    cibles: list[str] = field(default_factory=list)  # fichiers/dossiers relatifs au projet
    ids: list[str] = field(default_factory=list)  # ids testmon, filtrés par le plugin
    fichiers_filtres: list[str] = field(default_factory=list)  # où seuls `ids` sont gardés
    deselect: list[str] = field(default_factory=list)


def base_testmon(racine: Path) -> Path | None:
    """`.testmondata` du projet, sinon celle du même dossier dans le dépôt principal."""
    if (racine / ".testmondata").is_file():
        return racine / ".testmondata"
    commun = git(racine, "rev-parse", "--path-format=absolute", "--git-common-dir")
    haut = git(racine, "rev-parse", "--show-toplevel")
    if commun.returncode or haut.returncode:
        return None
    relatif = racine.resolve().relative_to(Path(haut.stdout.strip()).resolve())
    principal = Path(commun.stdout.strip()).parent / relatif / ".testmondata"
    return principal if principal.is_file() else None


def tests_testmon(base: Path, fichiers: list[str]) -> dict[str, set[str]]:
    """{fichier: ids des tests qui l'ont exécuté}, lu en lecture seule."""
    if not fichiers:
        return {}
    marques = ",".join("?" * len(fichiers))
    connexion = sqlite3.connect(f"file:{base.as_posix()}?mode=ro", uri=True)
    lignes = connexion.execute(
        "SELECT DISTINCT f.filename, te.test_name FROM test_execution te "
        "JOIN test_execution_file_fp x ON x.test_execution_id = te.id "
        f"JOIN file_fp f ON f.id = x.fingerprint_id WHERE f.filename IN ({marques})",
        fichiers).fetchall()
    connexion.close()
    resultat: dict[str, set[str]] = {}
    for fichier, test in lignes:
        resultat.setdefault(fichier, set()).add(test)
    return resultat


def _est_test(chemin: str) -> bool:
    nom = chemin.rsplit("/", 1)[-1]
    return nom.endswith(".py") and (nom.startswith("test_") or nom.endswith("_test.py")
                                    or nom == "conftest.py")


def _couvert(fichier: str, cibles: set[str]) -> bool:
    return any(fichier == c or fichier.startswith(c.rstrip("/") + "/") for c in cibles)


def selection_impactee(racine: Path) -> Selection:
    if git(racine, "rev-parse", "--git-dir").returncode:
        return Selection(f"impacted: {racine} n'est pas dans un dépôt git, aucun changement à "
                         f"suivre — passe targets=[...].")
    config = lire_config_tests(racine)
    nom_base, sha = base_de_la_branche(racine)
    changes = fichiers_changes(racine, sha)
    depuis = f"{nom_base} {sha[:8]}" if sha else "HEAD (ni develop ni master)"
    if not changes:
        return Selection(f"impacted: rien de modifié depuis {depuis} — aucun test lancé.")
    base = base_testmon(racine)
    par_testmon = tests_testmon(base, [c for c in changes if c.endswith(".py")]) if base else {}
    sources, cibles, ids = Counter(), set(), set()
    for chemin in changes:
        motifs = config.tests_pour(chemin)
        cibles.update(c for m in motifs for c in etendre(racine, m))
        sources["map"] += bool(motifs)
        if _est_test(chemin) and (racine / chemin).exists():
            cibles.add(chemin.rsplit("/", 1)[0] if chemin.endswith("conftest.py") else chemin)
            sources["test files"] += 1
        elif par_testmon.get(chemin):
            ids.update(par_testmon[chemin])
            sources["testmon"] += 1
        elif not motifs:
            sources["unmapped"] += 1
    always = {c for m in config.always for c in etendre(racine, m)}
    fichiers_ids = {i.split("::")[0] for i in ids if (racine / i.split("::")[0]).is_file()}
    filtres = sorted(f for f in fichiers_ids if not _couvert(f, cibles | always))
    tout = sorted(cibles | always | fichiers_ids)
    if not tout:
        return Selection(f"impacted: {len(changes)} fichiers changés depuis {depuis}, aucun test "
                         f"concerné ({_sources(sources)}) — rien lancé.")
    modifies = set(changes)
    deselect = [s for m in config.slow for s in etendre(racine, m) if s not in modifies]
    quoi = [f"{len(ids)} tests (testmon)"] if ids else []
    quoi += [f"{len(cibles - always)} targets"] if cibles - always else []
    ligne = (f"impacted: {' + '.join(quoi) or 'always seulement'} from {len(changes)} changed "
             f"files since {depuis} ({_sources(sources)})"
             + (f" + always {len(always)} targets" if always else "")
             + (f" ; slow écartés : {len(deselect)}" if deselect else "")
             + ("" if base else " ; testmon absent (.testmondata) : repli sur le mapping"))
    return Selection(ligne, tout, sorted(ids), filtres, deselect)


def _sources(sources: Counter) -> str:
    ordre = ("testmon", "map", "test files", "unmapped")
    return ", ".join(f"{nom} {sources[nom]}" for nom in ordre if sources[nom]) or "—"
