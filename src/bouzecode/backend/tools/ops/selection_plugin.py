# [desc] Plugin pytest injecté par RunPythonTest : garde seulement certains ids dans certains fichiers (sélection testmon, run sur la base) et écrit l'issue de chaque test dans un JSON. [/desc]
"""Pourquoi un plugin plutôt que des ids sur la ligne de commande : un id passé à pytest qui
n'existe pas (test renommé depuis la dernière base testmon, test NOUVEAU absent de develop)
fait échouer TOUTE la session (« ERROR: not found »). Ici on passe les fichiers, et le plugin
désélectionne ce qui n'est pas demandé ; un id introuvable est simplement absent des résultats.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

NOM_PLUGIN = "_bz_selection"

_SOURCE = '''\
"""Injecté par RunPythonTest (bouzecode) : sélection par ids et issue de chaque test."""
import json, os

_CONFIG = {}
if os.environ.get("BZ_SELECTION"):
    with open(os.environ["BZ_SELECTION"], encoding="utf-8") as _f:
        _CONFIG = json.load(_f)
_IDS = set(_CONFIG.get("ids", []))
_FILTRES = set(_CONFIG.get("fichiers_filtres", []))
_ISSUES = {}


def pytest_collection_modifyitems(session, config, items):
    if not _FILTRES:
        return
    gardes, retires = [], []
    for item in items:
        nodeid = item.nodeid
        demande = nodeid in _IDS or nodeid.split("[")[0] in _IDS
        (gardes if demande or nodeid.split("::")[0] not in _FILTRES else retires).append(item)
    if retires:
        config.hook.pytest_deselected(items=retires)
        items[:] = gardes


def pytest_collectreport(report):
    if report.failed:
        _ISSUES[report.nodeid] = "error"


def pytest_runtest_logreport(report):
    if report.failed:  # setup ou teardown en échec : "error", sans écraser un "failed" du call
        if report.when == "call" or _ISSUES.get(report.nodeid) != "failed":
            _ISSUES[report.nodeid] = "failed" if report.when == "call" else "error"
    elif report.when == "call" or report.skipped:
        _ISSUES.setdefault(report.nodeid, report.outcome)


def pytest_sessionfinish(session):
    sortie = os.environ.get("BZ_RESULTATS")
    if sortie and not hasattr(session.config, "workerinput"):
        with open(sortie, "w", encoding="utf-8") as f:
            json.dump(_ISSUES, f)
'''


def injecter_selection(env: dict, cmd_parts: list[str], ids: list[str] = (),
                       fichiers_filtres: list[str] = ()) -> tuple[str, Path]:
    """Écrit le plugin et sa config dans un dossier temporaire, l'ajoute au PYTHONPATH et à la
    commande. Rend (dossier à supprimer par l'appelant, chemin du JSON des issues)."""
    dossier = tempfile.mkdtemp(prefix="bz_sel_")
    (Path(dossier) / f"{NOM_PLUGIN}.py").write_text(_SOURCE, encoding="utf-8")
    config = Path(dossier) / "selection.json"
    config.write_text(json.dumps({"ids": list(ids), "fichiers_filtres": list(fichiers_filtres)}),
                      encoding="utf-8")
    env["BZ_SELECTION"] = str(config)
    env["BZ_RESULTATS"] = str(Path(dossier) / "issues.json")
    precedent = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = dossier + (os.pathsep + precedent if precedent else "")
    cmd_parts.extend(["-p", NOM_PLUGIN])
    return dossier, Path(env["BZ_RESULTATS"])


def lire_issues(chemin: Path) -> dict[str, str]:
    """{id: passed|failed|error|skipped} ; vide si le run n'a rien écrit (process tué, crash)."""
    return json.loads(chemin.read_text(encoding="utf-8")) if chemin.is_file() else {}


def nettoyer(dossier: str | None) -> None:
    if dossier:
        shutil.rmtree(dossier, ignore_errors=True)
