# [desc] DAG des outils : un RunPythonTest attend les Write/Edit qui le précèdent dans le même lot (le test lit les fichiers qu'ils écrivent) [/desc]
"""Session 859446f8a8bf (B4, 2026-10-14) : un lot `Write ×3 + RunPythonTest` sans `depends_on`.
Les outils d'un même niveau partent en parallèle : la vérification des cibles a tourné avant le
Write du fichier de test, d'où « cible introuvable » — et même une cible déjà présente aurait
été jouée contre les anciennes versions des modules réécrits dans le même lot. Un test lit tout
l'arbre, pas seulement sa cible : il attend TOUTES les écritures qui le précèdent dans le lot."""
from __future__ import annotations

import sys

_ECRITURES = ("Write", "Edit", "NotebookEdit")
_TESTS = ("RunPythonTest",)


def inject_write_test_deps(tool_calls: list[dict], deps: dict[str, set[str]]) -> None:
    ecritures: list[str] = []
    for tc in tool_calls:
        if tc["name"] in _ECRITURES:
            ecritures.append(tc["id"])
        elif tc["name"] in _TESTS and ecritures:
            manquantes = set(ecritures) - deps.get(tc["id"], set())
            if manquantes:
                deps.setdefault(tc["id"], set()).update(manquantes)
                print(f"[dag] auto-injected dependency: {tc['name']}({tc['id']}) now waits for "
                      f"{len(manquantes)} write(s) of the same batch", file=sys.stderr)
