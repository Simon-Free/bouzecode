# [desc] Plugin pytest `--only-changed[=REF]` : ne garde que les tests dont le code COUVERT (marqueur `couvre(*globs)`) a bougé dans git. [/desc]
"""Rejouer seulement les tests dont le code a bougé — y compris le code APPLICATIF.

`npx playwright test --only-changed` (runner JS) et `pytest --testmon` ne voient que ce que le
fichier de test importe ou exécute DANS son processus. Un test de bout en bout ouvre une URL :
le JS du Bureau et les routes Flask tournent dans le navigateur et dans un autre processus, ils
lui sont invisibles. Ici, chaque fichier de test DÉCLARE ce qu'il couvre :

    pytestmark = pytest.mark.couvre("static/js/bureau/**", "routes/work/micros/**")

et `pytest --only-changed` ne garde que les tests dont un glob touche un fichier modifié.

Règles :
- Fichiers modifiés = `git diff HEAD` (indexé + non indexé) + fichiers non suivis ;
  avec `--only-changed=REF` : en plus `git diff REF...HEAD` (les commits de la branche).
- Globs : relatifs à `src/bouzecode/web_v2/` (ini `only_changed_base`), sauf s'ils commencent
  par `src/`, `tests/`, `scripts/` ou `/` (alors relatifs à la racine du dépôt). `**` traverse
  les dossiers, `*` et `?` non.
- Un test SANS marqueur `couvre` est toujours gardé (on ne perd jamais un test par oubli).
- Toucher un chemin GLOBAL (design system, chrome commun, bac à sable, ce plugin, un conftest)
  rejoue tout.
- Un test est aussi gardé si son propre fichier a changé, ou un module d'appui (fichier .py
  non `test_*`) du même dossier.
- Sans git utilisable : avertissement, et tout est gardé.
- Un glob `couvre` qui ne désigne AUCUN fichier du dépôt (fichier renommé ou supprimé) est
  signalé : sinon le test ne serait plus jamais rejoué quand son vrai code bouge.

Chargé par défaut (`-p` dans `addopts`) mais INERTE sans l'option.
"""
from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

#  Changer l'un de ces fichiers peut casser n'importe quelle page : tout est rejoué.
GLOBAUX = (
    "static/ds.css",
    "static/app.css",
    "static/js/lib/**",
    "static/js/chrome.js",
    "templates/base.html",
    "app.py",
    "tests/sandbox/**",
    "src/bouzecode/web_v2/tests/pytest_only_changed.py",
    "/**/conftest.py",
    "/pyproject.toml",
)
RACINE = ("src/", "tests/", "scripts/", "/")


def pytest_addoption(parser):
    group = parser.getgroup("only-changed")
    group.addoption(
        "--only-changed", action="store", nargs="?", const="", default=None, metavar="REF",
        help="ne garder que les tests dont le code couvert (marqueur couvre) a changé ; "
             "sans REF : modifs non commitées, avec --only-changed=REF : aussi REF...HEAD",
    )
    parser.addini("only_changed_base", "base des globs de `couvre`", default="src/bouzecode/web_v2")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "couvre(*globs): code applicatif couvert par le test (pour --only-changed)")
    ref = config.getoption("only_changed")
    if ref and Path(ref).exists():
        raise pytest.UsageError(
            f"--only-changed a pris « {ref} » pour une référence git alors que c'est un chemin : "
            "écris --only-changed=REF, ou place --only-changed après les chemins.")


def _glob_regex(glob: str) -> re.Pattern:
    out, i = [], 0
    while i < len(glob):
        c = glob[i]
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if glob.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        out.append("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c))
        i += 1
    return re.compile("".join(out) + r"\Z")


def _absolu(glob: str, base: str) -> str:
    if glob.startswith("/"):
        return glob.lstrip("/")
    if glob.startswith(RACINE):
        return glob
    return f"{base.rstrip('/')}/{glob}"


@lru_cache(maxsize=None)
def _regex(glob: str, base: str) -> re.Pattern:
    return _glob_regex(_absolu(glob, base))


def _git(root: Path, *args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    return [l.strip() for l in out.stdout.splitlines() if l.strip()]


def changed_files(root: Path, ref: str) -> set[str]:
    files = set(_git(root, "diff", "--name-only", "HEAD"))
    files |= set(_git(root, "ls-files", "--others", "--exclude-standard"))
    if ref:
        files |= set(_git(root, "diff", "--name-only", f"{ref}...HEAD"))
    return files


def _touche(globs, changed: set[str], base: str) -> bool:
    regs = [_regex(g, base) for g in globs]
    return any(r.match(f) for r in regs for f in changed)


def globs_orphelins(items, root: Path, base: str) -> list[str]:
    """Les globs `couvre` qui ne correspondent à aucun fichier suivi ou non suivi du dépôt."""
    fichiers = set(_git(root, "ls-files")) | set(_git(root, "ls-files", "--others", "--exclude-standard"))
    globs = {g for item in items for m in item.iter_markers("couvre") for g in m.args}
    return sorted(g for g in globs if not _touche([g], fichiers, base))


def _garde(item, root: Path, changed: set[str], base: str) -> bool:
    marks = list(item.iter_markers("couvre"))
    if not marks:
        return True
    fichier = Path(str(item.fspath)).resolve()
    try:
        rel = fichier.relative_to(root).as_posix()
    except ValueError:
        return True
    if rel in changed:
        return True
    dossier = rel.rsplit("/", 1)[0] + "/"
    for f in changed:
        nom = f.rsplit("/", 1)[-1]
        if f.startswith(dossier) and "/" not in f[len(dossier):] and f.endswith(".py") \
                and not nom.startswith("test_"):
            return True
    globs = [g for m in marks for g in m.args]
    return _touche(globs, changed, base)


def pytest_collection_modifyitems(config, items):
    ref = config.getoption("only_changed")
    if ref is None:
        return
    rapport = config.pluginmanager.get_plugin("terminalreporter")
    ecrire = rapport.write_line if rapport and not hasattr(config, "workerinput") else (lambda _m: None)
    base = config.getini("only_changed_base")
    try:
        root = Path(_git(config.rootpath, "rev-parse", "--show-toplevel")[0]).resolve()
        changed = changed_files(root, ref)
    except (OSError, subprocess.CalledProcessError, IndexError) as exc:
        ecrire(f"only-changed : git inutilisable ({exc}) — tous les tests sont gardés")
        return
    orphelins = globs_orphelins(items, root, base)
    if orphelins:
        ecrire("only-changed : ATTENTION, globs couvre() qui ne désignent aucun fichier "
               f"(renommé ou supprimé ?) : {', '.join(orphelins)}")
    if _touche(GLOBAUX, changed, base):
        ecrire(f"only-changed : {len(changed)} fichiers modifiés, dont un chemin global "
               f"→ {len(items)} tests gardés / {len(items)}")
        return
    gardes, retires = [], []
    for item in items:
        (gardes if _garde(item, root, changed, base) else retires).append(item)
    if retires:
        config.hook.pytest_deselected(items=retires)
        items[:] = gardes
    ecrire(f"only-changed : {len(changed)} fichiers modifiés → {len(gardes)} tests gardés "
           f"/ {len(gardes) + len(retires)}")
