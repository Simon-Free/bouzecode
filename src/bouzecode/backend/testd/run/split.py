# [desc] testd : commande pytest d'un sous-run (plugin injecté, workers xdist), collecte navigateur / hors navigateur, avancement lu dans les événements [/desc]
"""La séparation se fait à la COLLECTE (`--collect-only -q` + le plugin), jamais en lisant les
sources : un test navigateur l'est par son marqueur ou par les fixtures qu'il demande, et seul
pytest connaît la clôture de fixtures réelle."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from ..common import reglages, sans_fenetre, tuer_arbre

DOSSIER_PLUGIN = str(Path(__file__).resolve().parent.parent / "plugin")


def sans_xdist(cmd: list[str]) -> list[str]:
    """La commande sans ses options xdist (`-n 4`, `-n4`, `--numprocesses=…`, `--dist …`)."""
    sortie, sauter = [], False
    for arg in cmd:
        if sauter:
            sauter = False
            continue
        if arg in ("-n", "--numprocesses", "--dist"):
            sauter = True
            continue
        if arg.startswith(("--numprocesses=", "--dist=")) or (arg.startswith("-n") and arg[2:].isdigit()):
            continue
        sortie.append(arg)
    return sortie


def workers_demandes(cmd: list[str]) -> int:
    """Nombre de workers xdist demandés par la commande (0 = sans xdist)."""
    for arg, suivant in zip(cmd, cmd[1:] + [""]):
        if arg in ("-n", "--numprocesses") and suivant.isdigit():
            return int(suivant)
        if arg.startswith("-n") and arg[2:].isdigit():
            return int(arg[2:])
        if arg.startswith("--numprocesses=") and arg.split("=", 1)[1].isdigit():
            return int(arg.split("=", 1)[1])
    return 0


def avec_workers(cmd: list[str], workers: int, vol: bool = False) -> list[str]:
    """La commande avec `-n <workers>` (sans xdist si 0 ou 1) ; `vol` : `--dist worksteal`,
    pour que la queue lente d'un worker soit reprise par les workers oisifs."""
    base = sans_xdist(cmd)
    if workers <= 1:
        return base
    return base + ["-n", str(workers)] + (["--dist", "worksteal"] if vol else [])


def env_sous_run(env: dict, dossier_evenements: Path, garder: str, marqueurs: str) -> dict:
    """Env d'un sous-run : plugin importable, groupe gardé, dossier des événements."""
    sortie = dict(env)
    precedent = sortie.get("PYTHONPATH", "")
    sortie["PYTHONPATH"] = DOSSIER_PLUGIN + (os.pathsep + precedent if precedent else "")
    sortie["BZ_TESTD_EVENTS"] = str(dossier_evenements)
    sortie["BZ_TESTD_KEEP"] = garder
    sortie["BZ_TESTD_BROWSER_MARKERS"] = marqueurs
    sortie["PYTHONUNBUFFERED"] = "1"
    if "BZ_RESULTATS" in sortie:  # issues du plugin de sélection : un fichier par sous-run
        sortie["BZ_RESULTATS"] = str(dossier_evenements / "issues.json")
    return sortie


def collecter(cmd: list[str], env: dict, cwd: str, dossier: Path, marqueurs: str,
              arreter=lambda: False, delai_s: float | None = None) -> tuple[dict | None, str]:
    """(`{"browser": [...], "other": [...], "deselected": {...}}`, note) par une collecte seule.
    Groupes None si elle échoue, dépasse `delai_s` ou si le job s'arrête : le job tourne alors
    d'un seul tenant, et le vrai run montre l'erreur de collecte.

    Job cd6cf0cd (2026-10-14) : la collecte de `tests/focus` a dépassé 180 s et le
    `subprocess.run(timeout=…)` levait TimeoutExpired, rendu en « erreur interne du démon » sans
    rien lancer — et ne tuait que le process direct. Ici l'ARBRE est tué et le job continue."""
    fichier = dossier / "collecte.json"
    env_collecte = env_sous_run(env, dossier, "", marqueurs)
    env_collecte["BZ_TESTD_SPLIT_OUT"] = str(fichier)
    env_collecte.pop("BZ_TESTD_EVENTS")
    env_collecte.pop("BZ_RESULTATS", None)
    commande = sans_xdist(cmd) + ["--collect-only", "-q", "-p", "_bz_testd_plugin"]
    delai = reglages()["collecte_s"] if delai_s is None else delai_s
    with open(dossier / "collecte.log", "w", encoding="utf-8") as journal:
        proc = subprocess.Popen(commande, cwd=cwd, env=env_collecte, stdout=journal,
                                stderr=subprocess.STDOUT, **sans_fenetre(groupe=True))
    fin = time.monotonic() + delai
    while proc.poll() is None:
        if arreter() or time.monotonic() > fin:
            tuer_arbre(proc.pid)
            proc.wait()
            return None, ("" if arreter() else
                          f"[testd] collecte interrompue après {delai:.0f} s (arbre de process tué) : "
                          f"tests lancés d'un seul tenant, sans séparation navigateur.\n")
        time.sleep(0.2)
    if proc.returncode not in (0, 5) or not fichier.exists():
        return None, (f"[testd] collecte en échec (code {proc.returncode}) : tests lancés d'un seul "
                      f"tenant, sans séparation navigateur.\n")
    return json.loads(fichier.read_text(encoding="utf-8")), ""


def lire_evenements(dossiers: list[Path]) -> dict:
    """Avancement d'un job : compteurs, échecs (avec extrait), test en cours le plus ancien."""
    debuts, fins = {}, {}
    for evenement in evenements(dossiers):
        if evenement["e"] == "start":
            debuts[evenement["id"]] = evenement["t"]
        elif evenement["e"] == "end" and (evenement["id"] not in fins or evenement["o"] == "error"):
            fins[evenement["id"]] = evenement
    issues = [f["o"] for f in fins.values()]
    en_cours = sorted((t, nodeid) for nodeid, t in debuts.items() if nodeid not in fins)
    return {
        "done": len(fins), "passed": issues.count("passed"), "skipped": issues.count("skipped"),
        "failed": issues.count("failed") + issues.count("error"),
        "failures": [{"id": f["id"], "excerpt": f.get("x", "")} for f in fins.values()
                     if f["o"] in ("failed", "error")],
        "longest": ({"id": en_cours[0][1], "elapsed_s": round(time.time() - en_cours[0][0], 1)}
                    if en_cours else None),
    }


def suivi_des_tests(dossiers: list[Path]) -> dict:
    """Pour la garde du délai par test : tests en cours (plus anciens d'abord, avec leur
    durée écoulée) et classes écrites à la collecte par le plugin (navigateur, marqueur `slow`)."""
    debuts, finis, navigateur, lents = {}, set(), set(), set()
    for evenement in evenements(dossiers):
        if evenement["e"] == "start":
            debuts[evenement["id"]] = evenement["t"]
        elif evenement["e"] == "end":
            finis.add(evenement["id"])
        elif evenement["e"] == "classes":
            navigateur.update(evenement["navigateur"])
            lents.update(evenement["lent"])
    maintenant = time.time()
    en_cours = sorted((t, nodeid) for nodeid, t in debuts.items() if nodeid not in finis)
    return {"en_cours": [(nodeid, maintenant - t) for t, nodeid in en_cours],
            "navigateur": navigateur, "lents": lents}


def durees_mesurees(dossiers: list[Path]) -> dict:
    """{nodeid: secondes (setup + call + teardown)} des tests finis de ce job."""
    return {e["id"]: e["d"] for e in evenements(dossiers) if e["e"] == "dur"}


def evenements(dossiers: list[Path]):
    """Tous les événements JSON des dossiers, ligne en cours d'écriture exclue."""
    for dossier in dossiers:
        for fichier in sorted(dossier.glob("*.jsonl")) if dossier.exists() else []:
            for ligne in fichier.read_text(encoding="utf-8", errors="replace").splitlines():
                if ligne.endswith("}"):  # sinon : ligne en cours d'écriture
                    yield json.loads(ligne)
