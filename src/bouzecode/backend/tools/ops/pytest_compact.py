# [desc] Sortie pytest → résultat minimal pour le modèle : échecs et erreurs d'abord, rien d'autre sur un run vert ; vues optionnelles `show` (warnings, durations, passed, full). [/desc]
"""Chaque caractère renvoyé est payé en tokens frais : on ne montre que ce qui sert.

- Vert : la ligne de verdict, plus au plus 5 tests ≥ 1 s. Ni warnings, ni liste des tests.
- Rouge : par échec l'extrait utile (`pytest_failures.extrait_d_echec`), le short test summary,
  les warnings levés dans les fichiers en échec (dédoublonnés), le verdict, et le chemin de la
  sortie complète. Les erreurs de collecte (section ERRORS) passent avant les échecs.
- Toute section `=== titre ===` inconnue (plugin) est montrée, bornée : un plugin qui écrit
  une section a quelque chose à dire, mais pas 400 lignes.
- `show` élargit : 'warnings' (tous, dédoublonnés), 'durations' (la section entière),
  'passed' (les tests passés), 'full' (la sortie brute, bornée comme toute sortie d'outil).
Une sortie qui n'est pas du pytest est rendue telle quelle.
"""
from __future__ import annotations

import os
import re
import time

from .env_diagnosis import regrouper, rendu_groupes
from .pytest_failures import _couper_milieu, blocs_d_echec, extrait_d_echec
from .pytest_sections import (
    SEUIL_LENT_S, SortiePytest, est_pytest, fichiers_en_echec, lire, tests_lents,
    warnings_dedoublonnes,
)
from .truncation import _get_output_dir, truncate_tool_output

VUES = ("warnings", "durations", "passed", "full")
MAX_CHARS = 8000
MIN_PAR_ECHEC = 700
MAX_PAR_ECHEC = 1500
LIGNES_PAR_SECTION_INCONNUE = 8
_CONNUES = {"FAILURES", "ERRORS", "short test summary info", "warnings summary",
            "slowest durations", "test session starts", "PASSES"}
_PASSE_RE = re.compile(r"^(\S+::\S+) PASSED|PASSED (\S+::\S+)")


def _section_inconnue(titre: str, lignes: list[str]) -> str:
    corps = [l.rstrip()[:200] for l in lignes if l.strip()]
    reste = len(corps) - LIGNES_PAR_SECTION_INCONNUE
    suite = [f"… (+{reste} lignes)"] if reste > 0 else []
    return "\n".join([f"=== {titre} ===", *corps[:LIGNES_PAR_SECTION_INCONNUE], *suite])


def _warnings(lu: SortiePytest, show, resume: list[str]) -> list[str]:
    lignes = lu.section("warnings summary")
    if not lignes:
        return []
    if "warnings" in show:
        return ["warnings :\n" + warnings_dedoublonnes(lignes)]
    if lu.vert or not resume:
        return []
    texte = warnings_dedoublonnes(lignes, fichiers_en_echec(resume), max_chars=1200)
    return [f"warnings des fichiers en échec :\n{texte}"] if texte else []


def _durees(lu: SortiePytest, show) -> list[str]:
    lignes = lu.section("slowest durations")
    if "durations" in show:
        lentes = tests_lents(lignes, tout=True)
        return ["durées :\n" + "\n".join(lentes)] if lentes else []
    lentes = tests_lents(lignes) if lu.vert else []
    return [f"tests lents (≥ {SEUIL_LENT_S:g} s) :\n" + "\n".join(lentes)] if lentes else []


def _passes(output: str) -> list[str]:
    noms = [m.group(1) or m.group(2) for l in output.split("\n") if (m := _PASSE_RE.search(l.strip()))]
    return [f"tests passés ({len(noms)}) :\n" + "\n".join(noms[:60])] if noms else []


def _echecs(groupes: list, disponible: int) -> list[str]:
    """Un extrait par SIGNATURE (cf. env_diagnosis) : 144 fois la même erreur = un extrait."""
    blocs = [blocs_du_groupe[0] for _, _, blocs_du_groupe in groupes]
    if not blocs:
        return []
    par_echec = min(MAX_PAR_ECHEC, max(MIN_PAR_ECHEC, disponible // len(blocs)))
    montres = max(1, min(len(blocs), disponible // par_echec))
    extraits = [extrait_d_echec(nom, bloc, par_echec) for nom, bloc in blocs[:montres]]
    if montres < len(blocs):
        extraits.append(f"(+{len(blocs) - montres} autres échecs : détail dans la sortie complète)")
    return extraits


def compact_pytest_output(output: str, show=(), max_chars: int = MAX_CHARS) -> str:
    """Le strict utile d'une sortie pytest (cf. docstring du module) ; non-pytest : inchangé."""
    if not est_pytest(output) or "full" in show:
        return output
    lu = lire(output)
    resume = [l.rstrip()[:250] for l in lu.section("short test summary info") if l.strip()]
    groupes = regrouper(blocs_d_echec(lu.section("ERRORS") + lu.section("FAILURES")))
    ids = [l.split()[1] for l in resume if l.startswith(("FAILED ", "ERROR ")) and " " in l]
    #  Regroupé : la section remplace le résumé ligne à ligne (liste complète : sortie sauvée).
    regroupement = rendu_groupes(groupes, ids, lu.section("slowest durations"))
    autres = [regroupement] if regroupement else []
    autres += [*lu.crashs[:10], *lu.interruptions]
    autres += [_section_inconnue(t, l) for t, l in lu.sections if t not in _CONNUES]
    autres += ["\n".join(resume)] if resume and not regroupement else []
    autres += _warnings(lu, show, resume) + _durees(lu, show)
    autres += _passes(output) if "passed" in show else []
    disponible = max_chars - sum(len(p) + 2 for p in autres) - len(lu.verdict) - 300
    echecs = _echecs(groupes, disponible)
    if not lu.verdict and not echecs:
        return output  # ni verdict ni échec lisible (process tué, crash) : rien à résumer
    if regroupement:  # la vue d'ensemble d'abord, puis un extrait par signature
        echecs, autres = autres[:1] + echecs, autres[1:]
    return "\n\n".join([*echecs, *autres, lu.verdict] if lu.verdict else [*echecs, *autres])


def _rien_d_utile_coupe(lu: SortiePytest) -> bool:
    """Run vert dont aucune section de plugin n'a été raccourcie : pas de sortie à pointer."""
    return lu.vert and all(sum(1 for l in lignes if l.strip()) <= LIGNES_PAR_SECTION_INCONNUE
                           for titre, lignes in lu.sections if titre not in _CONNUES)


def _ecrire(sortie: str, tool_name: str):
    chemin = _get_output_dir() / f"{tool_name.lower()}_{int(time.time() * 1000)}_{os.getpid()}.txt"
    chemin.write_text(sortie, encoding="utf-8")
    return chemin


def _sauver(sortie: str, tool_name: str) -> str:
    #  Format lu par web_v2 formatter.resolve_overflow_pointer.
    return (f"[...output truncated — {sortie.count(chr(10)) + 1} lines total, "
            f"full output saved to: {_ecrire(sortie, tool_name)}]")


def rendu_pytest(sortie: str, show=(), tool_name: str = "RunPythonTest",
                 max_chars: int = MAX_CHARS, toujours_sauver: bool = False) -> str:
    """Résultat borné à `max_chars`. Hors run vert, la sortie complète est sauvée et son chemin
    donné en dernière ligne ; `toujours_sauver` : aussi sur un run vert (RunPythonTest)."""
    compacte = compact_pytest_output(sortie, show, max_chars)

    def pointeur() -> str:
        return f"\n[full output saved to: {_ecrire(sortie, tool_name)}]" if toujours_sauver else ""
    if compacte is sortie:
        rendu = truncate_tool_output(sortie, tool_name, max_chars=max_chars)
        return rendu + pointeur() if rendu == sortie else rendu
    if _rien_d_utile_coupe(lire(sortie)) and len(compacte) <= max_chars:
        return compacte + pointeur()
    marqueur = _sauver(sortie, tool_name)
    return _couper_milieu(compacte, max_chars - len(marqueur) - 1) + "\n" + marqueur
