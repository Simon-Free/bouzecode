# [desc] Plugin pytest injecté par testd : classe navigateur / hors navigateur, filtre un groupe, journalise début, fin et échecs de chaque test [/desc]
"""Chargé par `-p _bz_testd_plugin` (son dossier en tête de PYTHONPATH). Piloté par l'env :

- `BZ_TESTD_SPLIT_OUT` : écrit `{"browser": [...], "other": [...], "deselected": {marqueur: n}}`
  (nodeids) après la collecte ;
- `BZ_TESTD_KEEP` = `browser` | `other` : ne garde que ce groupe (le reste est désélectionné) ;
- `BZ_TESTD_BROWSER_MARKERS` : marqueurs qui désignent un test navigateur (`browser,e2e`) ;
- `BZ_TESTD_EVENTS` : dossier où écrire un événement JSON par ligne (début, fin, échec).

Sous xdist, seul le contrôleur écrit les événements : il reçoit `logstart` et les rapports de
tous les workers ; un worker qui écrirait aussi les doublerait."""
import json
import sys
import os
import time
from pathlib import Path

import pytest

_FIXTURES_NAVIGATEUR = {"page", "browser", "context", "authenticated_page"}
_config = None


def _marqueurs_navigateur() -> list[str]:
    brut = os.environ.get("BZ_TESTD_BROWSER_MARKERS") or "browser,e2e"
    return [m.strip() for m in brut.split(",") if m.strip()]


_LANCEURS = ("sync_playwright", "async_playwright")


def _origine(valeur) -> str:
    origine = getattr(valeur, "__module__", None) or getattr(valeur, "__name__", "")
    return origine if isinstance(origine, str) else ""


def _module_lance_un_navigateur(nom: str) -> bool:
    """Un module d'aide (pas Playwright lui-même) qui détient un LANCEUR de navigateur
    (`sync_playwright`) : importer `Page` pour une annotation ne compte pas."""
    module = sys.modules.get(nom)
    if module is None or nom.startswith(("playwright", "pytest_playwright")):
        return False
    return any(_origine(vars(module).get(lanceur)).startswith("playwright") for lanceur in _LANCEURS)


def _module_pilote_playwright(module) -> bool:
    """Le module de test a importé Playwright (`from playwright.sync_api import sync_playwright`),
    ou une aide qui lance son navigateur : lu dans l'objet module collecté, pas dans le source.

    Session B4 (2026-10-14) : les tests d'exercices de demoapp_clone importent
    `tools.exercises.harness.exercise_session`, qui démarre uvicorn et Chromium à chaque test.
    Classés « hors navigateur », ils ne recevaient ni le navigateur chaud ni la réserve de
    contextes : 4 agents lançaient leurs navigateurs en même temps, un test passait de 8,7 à
    152 s."""
    for valeur in vars(module).values() if module is not None else ():
        origine = _origine(valeur)
        if origine.startswith("playwright") or (origine and _module_lance_un_navigateur(origine)):
            return True
    return False


def _fixture_playwright(definitions) -> bool:
    """La fixture vient de pytest-playwright, ou d'un module qui importe Playwright. Un `page`
    maison qui rend du HTML par TestClient (demoapp_clone, test_demoapp_home.py) n'en est pas une."""
    for definition in (definitions or ())[-1:]:  # la définition active (la plus proche)
        module = getattr(definition.func, "__module__", "") or ""
        if module.startswith(("pytest_playwright", "playwright")):
            return True
        if _module_pilote_playwright(sys.modules.get(module)):
            return True
    return False


def est_navigateur(item) -> bool:
    if any(item.get_closest_marker(m) for m in _marqueurs_navigateur()):
        return True
    definitions = getattr(getattr(item, "_fixtureinfo", None), "name2fixturedefs", {})
    demandees = _FIXTURES_NAVIGATEUR & set(getattr(item, "fixturenames", ()))
    if any(_fixture_playwright(definitions.get(nom)) for nom in demandees):
        return True
    return _module_pilote_playwright(getattr(item, "module", None))


def pytest_configure(config):
    global _config
    _config = config


def _plus_longs_d_abord(items) -> None:
    """Fichiers les plus longs d'abord (durées passées), ordre gardé DANS un fichier : trier
    test par test recréerait les fixtures de module. Même fichier figé pour tous les workers
    xdist, sinon leurs collectes divergent."""
    chemin = os.environ.get("BZ_TESTD_DURATIONS")
    if not chemin or not Path(chemin).exists():
        return
    durees = json.loads(Path(chemin).read_text(encoding="utf-8"))
    par_fichier: dict = {}
    for item in items:
        fichier = item.nodeid.split("::", 1)[0]
        par_fichier[fichier] = par_fichier.get(fichier, 0.0) + durees.get(item.nodeid, 0.5)
    items.sort(key=lambda item: -par_fichier[item.nodeid.split("::", 1)[0]])


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session, config, items):
    _plus_longs_d_abord(items)
    garder = os.environ.get("BZ_TESTD_KEEP")
    if garder not in ("browser", "other"):
        return
    navigateur = [i for i in items if est_navigateur(i)]
    autres = [i for i in items if not est_navigateur(i)]
    gardes, ecartes = (navigateur, autres) if garder == "browser" else (autres, navigateur)
    if ecartes:
        config.hook.pytest_deselected(items=ecartes)
        items[:] = gardes


_MARQUEURS_TECHNIQUES = {"parametrize", "usefixtures", "filterwarnings", "timeout", "skip",
                         "skipif", "xfail"}
_ecartes: dict = {}


def pytest_deselected(items):
    """Collecte seule : marqueurs des tests désélectionnés (par `-m`, `-k`, un plugin), pour
    dire au modèle pourquoi 0 test n'a tourné et quel `marker=` les lance."""
    if not os.environ.get("BZ_TESTD_SPLIT_OUT"):
        return
    for item in items:
        noms = {m.name for m in item.iter_markers()} - _MARQUEURS_TECHNIQUES
        for nom in noms or {"(aucun marqueur)"}:
            _ecartes[nom] = _ecartes.get(nom, 0) + 1


def pytest_collection_finish(session):
    """Après TOUTES les désélections (celles des conftest `trylast` comprises)."""
    sortie = os.environ.get("BZ_TESTD_SPLIT_OUT")
    if sortie:
        navigateur = [i.nodeid for i in session.items if est_navigateur(i)]
        autres = [i.nodeid for i in session.items if not est_navigateur(i)]
        Path(sortie).write_text(json.dumps({"browser": navigateur, "other": autres,
                                            "deselected": _ecartes}), encoding="utf-8")
    _ecrire_classes(session.items)


def _ecrire_classes(items) -> None:
    """Tests navigateur et tests marqués `slow` : le démon en tire la limite de chaque test
    (cf. garde.limites). Écrit aussi par les workers xdist (ce sont eux qui collectent) ; les
    doublons ne gênent pas, le démon en fait des ensembles."""
    navigateur = [i.nodeid for i in items if est_navigateur(i)]
    lents = [i.nodeid for i in items if i.get_closest_marker("slow")]
    if navigateur or lents:
        _ecrire({"e": "classes", "navigateur": navigateur, "lent": lents}, workers_aussi=True)


def _ecrire(evenement: dict, workers_aussi: bool = False) -> None:
    dossier = os.environ.get("BZ_TESTD_EVENTS")
    if not dossier or (not workers_aussi and _config is not None and hasattr(_config, "workerinput")):
        return
    evenement["t"] = time.time()
    with open(Path(dossier) / f"{os.getpid()}.jsonl", "a", encoding="utf-8") as fichier:
        fichier.write(json.dumps(evenement) + "\n")


def pytest_runtest_logstart(nodeid, location):
    _ecrire({"e": "start", "id": nodeid})


_durees: dict = {}


def pytest_runtest_logreport(report):
    _durees[report.nodeid] = _durees.get(report.nodeid, 0.0) + report.duration
    if report.when == "teardown":
        _ecrire({"e": "dur", "id": report.nodeid, "d": _durees.pop(report.nodeid)})
    if report.when == "call":
        issue = report.outcome
    elif report.failed:
        issue = "error"  # setup ou teardown en échec
    elif report.when == "setup" and report.skipped:
        issue = "skipped"
    else:
        return
    evenement = {"e": "end", "id": report.nodeid, "o": issue}
    if report.when == "call":
        evenement["c"] = round(report.duration, 3)  # phase d'appel seule : le signal « lent »
    if report.failed:
        evenement["x"] = "\n".join(report.longreprtext.splitlines()[-12:])
    _ecrire(evenement)
