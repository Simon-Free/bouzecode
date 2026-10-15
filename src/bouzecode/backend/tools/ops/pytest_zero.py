# [desc] RunPythonTest : un run qui n'a lancé AUCUN test le dit, avec le verdict de pytest, ce qui a désélectionné (-m des addopts du projet, -m/-k de l'appel, sélection, --deselect) et l'appel qui les lance [/desc]
"""Session de4d1304 (2026-10-14), jobs 1c757948, 396e7ca4, f2f9e3ac, 51aeb8bb : les addopts de
demo_application portent `-m 'not llm and not network'`, les 4 tests ciblés étaient `network`.
pytest disait « no tests collected (4 deselected) », le modèle ne voyait qu'un rapport vide et a
contourné l'outil 6 fois. Un `-m` passé à pytest REMPLACE celui des addopts : `marker='network'`
suffit à les lancer."""
from __future__ import annotations

import configparser
import json
import re
import shlex
import tomllib
from pathlib import Path

_VERDICT_RE = re.compile(r"^=*\s*(.*\bin \d+(?:\.\d+)?s\b.*?)\s*=*$")
_ISSUE_RE = re.compile(r"\b\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed)\b")
_DESELECT_RE = re.compile(r"(\d+) deselected")
_MOTS_LOGIQUES = {"and", "or", "not"}


def verdict(sortie: str) -> str:
    """La dernière ligne de résumé de pytest (« 4 deselected in 2.43s »), "" sinon."""
    for ligne in reversed(sortie.splitlines()):
        trouve = _VERDICT_RE.match(ligne.strip())
        if trouve:
            return trouve.group(1)
    return ""


def aucun_test_lance(sortie: str) -> bool:
    """pytest a conclu sans un seul test passé, échoué, en erreur ou sauté."""
    final = verdict(sortie)
    return bool(final) and not _ISSUE_RE.search(final)


def _option(arguments: list[str], nom: str) -> str | None:
    """Dernière valeur de `-m` / `-k` dans des arguments pytest (`-m x` ou `-mx`)."""
    valeur = None
    for i, argument in enumerate(arguments):
        if argument == nom and i + 1 < len(arguments):
            valeur = arguments[i + 1]
        elif argument.startswith(nom) and len(argument) > 2 and not argument.startswith("--"):
            valeur = argument[2:]
    return valeur


def addopts_du_projet(racine: Path) -> tuple[list[str], str]:
    """(addopts, fichier) de la config pytest du projet, dans l'ordre de recherche de pytest."""
    for nom, section in (("pytest.ini", "pytest"), ("pyproject.toml", None), ("tox.ini", "pytest"),
                         ("setup.cfg", "tool:pytest")):
        fichier = racine / nom
        if not fichier.is_file():
            continue
        if section is None:
            options = tomllib.loads(fichier.read_text(encoding="utf-8")).get("tool", {}) \
                .get("pytest", {}).get("ini_options")
            if options is None:
                continue
            brut = options.get("addopts", "")
        else:
            lecteur = configparser.ConfigParser(interpolation=None)
            lecteur.read(fichier, encoding="utf-8")
            if not lecteur.has_section(section):
                continue
            brut = lecteur.get(section, "addopts", fallback="")
        brut = " ".join(brut) if isinstance(brut, list) else brut
        return shlex.split(brut, posix=True), nom
    return [], ""


def explication(cmd: list[str], racine: Path, env: dict, sortie: str,
                marqueurs_ecartes: dict | None = None) -> str:
    """Le paragraphe « 0 test lancé » ; `marqueurs_ecartes` : {marqueur: nombre} des tests
    désélectionnés, quand la collecte les a comptés (démon)."""
    options = cmd[cmd.index("pytest") + 1:] if "pytest" in cmd else cmd
    final = verdict(sortie) or "(pas de ligne de résumé)"
    ecartes = _DESELECT_RE.search(sortie)
    nombre = int(ecartes.group(1)) if ecartes else 0
    erreurs = [l.strip() for l in sortie.splitlines() if l.startswith("ERROR")][:5]
    lignes = [f"[RunPythonTest] verdict de pytest : « {final} »."]
    if not nombre:
        lignes.append("0 test lancé, aucun désélectionné : rien n'a été collecté dans les cibles"
                      + (" :\n  " + "\n  ".join(erreurs) if erreurs else
                         " (fichier sans test, nom hors `python_files`, ou `collect_ignore`)."))
        return "\n".join(lignes) + "\n"
    addopts, fichier = addopts_du_projet(racine)
    m_appel, m_projet = _option(options, "-m"), _option(addopts + shlex.split(
        env.get("PYTEST_ADDOPTS", "")), "-m")
    causes = []
    if m_appel is not None:
        causes.append(f"-m '{m_appel}' (marker= de l'appel)")
    elif m_projet is not None:
        causes.append(f"-m '{m_projet}' (addopts du projet, {fichier or 'PYTEST_ADDOPTS'})")
    if _option(options, "-k") is not None:
        causes.append(f"-k '{_option(options, '-k')}' (keyword=)")
    if "--deselect" in options:
        causes.append(f"--deselect ×{options.count('--deselect')} (tests lents écartés de la sélection)")
    selection = Path(env.get("BZ_SELECTION") or "")
    if selection.is_file() and json.loads(selection.read_text(encoding="utf-8")).get("ids"):
        causes.append("la sélection des tests impactés (ids)")
    cause = causes[0] if len(causes) == 1 else "l'un de : " + " ; ".join(causes or ["un plugin"])
    lignes.append(f"0 test lancé : {nombre} désélectionné(s) par {cause}."
                  + (" Marqueurs des tests écartés : " + ", ".join(
                      f"{m} ×{n}" for m, n in sorted(marqueurs_ecartes.items())) + "."
                     if marqueurs_ecartes else ""))
    expression = m_appel if m_appel is not None else m_projet
    if expression is not None:
        lignes.append(_remede_marqueur(expression, marqueurs_ecartes))
    return "\n".join(lignes) + "\n"


def _remede_marqueur(expression: str, marqueurs_ecartes: dict | None) -> str:
    noms = [n for n in re.findall(r"[A-Za-z_]\w*", expression) if n not in _MOTS_LOGIQUES]
    vises = [n for n in noms if marqueurs_ecartes and n in marqueurs_ecartes] or noms
    proposition = " or ".join(dict.fromkeys(vises))
    return (f"Pour les lancer : marker='{proposition}' (un -m passé par marker= REMPLACE celui des "
            f"addopts, il ne s'y ajoute pas).")

