# [desc] Fonctions pures triant/regroupant un git diff + recap en payload sectionné pour l'endpoint recap [/desc]
"""Fonctions PURES (aucun git/IO) qui transforment un `git diff` brut + le recap
persisté en payload prêt à afficher, pour que le front reste bête.

Payload : ``{recap, recap_missing, diffs:[{file, patch, is_test, is_new, section}]}``
- ``section`` ∈ {"changes", "other", "tests", "all"} : le front n'a qu'à afficher
  les en-têtes de section, aucun tri/regroupement côté client.
- Ordre (recap présent) : les fichiers non-test listés dans ``recap.changes`` dans
  CET ordre (section "changes"), puis les autres non-test hors changes (section
  "other" = « Autres modifications »), puis tous les ``test_*.py`` (section "tests" :
  nouveaux d'abord, puis corrigés).
- Fallback (recap absent/vide) : ``recap_missing=True`` et tous les fichiers triés
  alphabétiquement en section "all".
"""
from __future__ import annotations

import posixpath
import re

_DIFF_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)


def _is_test_path(path: str) -> bool:
    """test_*.py par basename, OU un segment `tests` dans le chemin."""
    norm = path.replace("\\", "/")
    base = posixpath.basename(norm)
    if base.startswith("test_") and base.endswith(".py"):
        return True
    return "/tests/" in norm or norm.startswith("tests/")


def split_unified_diff(diff_text: str) -> list[dict]:
    """Découpe un `git diff` en blocs par fichier.

    Chaque bloc = {file, patch, is_test, is_new}. `file` = le chemin `b/` (nouveau
    nom). `is_new` = le bloc contient `new file mode` (fichier créé)."""
    if not diff_text or not diff_text.strip():
        return []
    matches = list(_DIFF_HEADER.finditer(diff_text))
    blocks: list[dict] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(diff_text)
        patch = diff_text[start:end].rstrip("\n") + "\n"
        file_path = match.group(2)
        blocks.append({
            "file": file_path,
            "patch": patch,
            "is_test": _is_test_path(file_path),
            "is_new": "new file mode" in patch,
        })
    return blocks


def _recap_change_files(recap: dict | None) -> list[str]:
    """Liste ordonnée des `file` déclarés dans recap.changes (tolère les entrées mal formées)."""
    if not isinstance(recap, dict):
        return []
    changes = recap.get("changes")
    if not isinstance(changes, list):
        return []
    files: list[str] = []
    for entry in changes:
        if isinstance(entry, dict) and isinstance(entry.get("file"), str):
            files.append(entry["file"])
    return files


def build_recap_payload(recap: dict | None, diff_text: str) -> dict:
    """Assemble le payload de l'endpoint recap. Fonction PURE (testable seule)."""
    blocks = split_unified_diff(diff_text)
    recap_present = isinstance(recap, dict) and bool(recap)

    if not recap_present:
        ordered = sorted(blocks, key=lambda b: b["file"].lower())
        diffs = [_with_section(b, "all") for b in ordered]
        return {"recap": recap if isinstance(recap, dict) else None,
                "recap_missing": True, "diffs": diffs}

    tests = [b for b in blocks if b["is_test"]]
    non_tests = [b for b in blocks if not b["is_test"]]
    by_file = {b["file"]: b for b in non_tests}

    # section "changes" : ordre de recap.changes, dédupliqué, uniquement fichiers présents dans le diff.
    changes_order = _recap_change_files(recap)
    seen: set[str] = set()
    change_blocks: list[dict] = []
    for file_path in changes_order:
        block = by_file.get(file_path)
        if block is not None and file_path not in seen:
            change_blocks.append(_with_section(block, "changes"))
            seen.add(file_path)

    # section "other" : non-test hors changes, ordre alpha stable.
    other_blocks = [_with_section(b, "other")
                    for b in sorted(non_tests, key=lambda b: b["file"].lower())
                    if b["file"] not in seen]

    # section "tests" : nouveaux d'abord (is_new), puis corrigés ; alpha dans chaque groupe.
    new_tests = sorted((b for b in tests if b["is_new"]), key=lambda b: b["file"].lower())
    fixed_tests = sorted((b for b in tests if not b["is_new"]), key=lambda b: b["file"].lower())
    test_blocks = [_with_section(b, "tests") for b in (*new_tests, *fixed_tests)]

    return {"recap": recap, "recap_missing": False,
            "diffs": [*change_blocks, *other_blocks, *test_blocks]}


def _with_section(block: dict, section: str) -> dict:
    """Copie exposée au front : {file, patch, is_test, is_new, section}."""
    return {"file": block["file"], "patch": block["patch"],
            "is_test": block["is_test"], "is_new": block["is_new"], "section": section}
