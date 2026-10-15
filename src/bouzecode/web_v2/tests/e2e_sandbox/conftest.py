# [desc] Conftest des E2E du bac à sable : vérificateur d'invariants ACTIF pendant chaque test (échec si une incohérence d'interface apparaît et dure), désactivable par @pytest.mark.sans_invariants. [/desc]
"""Branche `invariants.Surveillant` sur chaque E2E de ce dossier.

Les URLs surveillées sont celles des bacs à sable visés (BZ_E2E_URL, BZ_E2E_URL_AGENTS,
BZ_E2E_URL_BUREAU, BZ_E2E_URL_PROFILS). Sans URL, rien n'est surveillé.

Une violation déjà présente au DÉBUT du test (héritée des données restaurées ou d'un test
précédent) ne fait pas échouer ce test-ci : elle est listée une fois dans le résumé de session.
Seules les violations APPARUES pendant le test, et qui durent, le font échouer.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import invariants  # noqa: E402

_BASES = sorted({u.rstrip("/") for u in (os.environ.get(k, "") for k in (
    "BZ_E2E_URL", "BZ_E2E_URL_AGENTS", "BZ_E2E_URL_BUREAU", "BZ_E2E_URL_PROFILS")) if u})
_HERITEES: dict[str, str] = {}


def _cles_presentes(base: str) -> set:
    inst = invariants.instantane(base)
    #  Les compteurs sont globaux : ni relevés (un instantané ne prouve pas un écart qui dure),
    #  ni exclus de la surveillance (un écart qui dure pendant le test le fait échouer).
    vues = invariants.a_signaler_au_depart(invariants.violations(inst))
    for v in vues:
        _HERITEES.setdefault(f"{v.regle}:{v.cle}", v.preuve)
    return {(base, v.regle, v.cle) for v in vues}


@pytest.fixture(autouse=True)
def invariants_de_l_interface(request):
    if not _BASES or request.node.get_closest_marker("sans_invariants"):
        yield
        return
    heritees = set().union(*(_cles_presentes(b) for b in _BASES))
    surveillant = invariants.Surveillant(_BASES, ignorer=heritees).demarrer()
    yield
    violations = surveillant.arreter()
    if violations:
        pytest.fail("Invariants de l'interface violés pendant le test :\n  " + "\n  ".join(violations),
                    pytrace=False)


def pytest_terminal_summary(terminalreporter):
    if _HERITEES:
        terminalreporter.section("invariants déjà violés au début des tests (données héritées)")
        for cle, preuve in sorted(_HERITEES.items()):
            terminalreporter.write_line(f"{cle} — {preuve}")
