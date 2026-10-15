# [desc] testd : RunPythonTest passe par le démon (attente avec position et avancement, ou retour immédiat d'un job_id) ; l'outil TestStatus [/desc]
"""Mesuré le 2026-10-13 : le modèle attendait à l'aveugle (attentes de 600 s) un run dont la
progression n'allait qu'au terminal. `RunPythonTest(wait=false)` rend un `job_id` tout de suite,
et `TestStatus` donne au modèle ce que le terminal voyait : position en file, n/N, échecs avec
leur extrait dès qu'ils arrivent, test le plus long en cours, puis le rapport compact."""
from __future__ import annotations

import time
from pathlib import Path

from . import client

MAX_ATTENTE_S = 600
_SONDAGE_S = 0.5
_ECHECS_MONTRES = 10
_LONG_DES_S = 10        # le test le plus long n'est cité qu'à partir de 10 s
_TEST_COURT_MAX = 60


def ligne_avancement(etat: dict) -> str:
    if etat["state"] == "queued":
        return (f"pytest: en file d'attente, position {etat['position']} depuis {etat['queued_s']:.0f} s "
                f"({etat.get('budget', '')})")
    if etat["total"] is None and not etat["done"]:
        return "pytest: collecte des tests…"
    total = etat["total"] or etat["done"]
    parallele = f" · -n {etat['workers']}" if etat.get("workers") else ""
    ligne = (f"pytest: {etat['done']}/{total} , ✅{etat['passed']} ❌{etat['failed']} "
             f"⏭{etat['skipped']}{parallele}")
    if etat.get("browser_position"):
        ligne += (f" · tests navigateur en attente d'un créneau, position {etat['browser_position']} "
                  f"({etat.get('browser_slots', '')})")
    if etat.get("longest") and etat["longest"]["elapsed_s"] >= _LONG_DES_S:
        longest = etat["longest"]
        ligne += (f" · le plus long : {nom_de_test_court(longest['id'])} "
                  f"({duree_par_paliers(longest['elapsed_s'])})")
    return ligne


def nom_de_test_court(node_id: str) -> str:
    """`src/a/b/test_x.py::test_y` -> `test_x.py::test_y`, coupé à ~60 caractères : la ligne
    tient dans la barre des agents et l'onglet d'un sous-agent."""
    fichier, sep, reste = node_id.partition("::")
    court = fichier.replace("\\", "/").rsplit("/", 1)[-1] + sep + reste
    return court if len(court) <= _TEST_COURT_MAX else court[:_TEST_COURT_MAX - 1] + "…"


def duree_par_paliers(secondes: float) -> str:
    """10 s, 20 s, 30 s… puis 1 min, 2 min… : la ligne ne change pas à chaque seconde."""
    if secondes < 60:
        return f"{int(secondes // 10) * 10} s"
    return f"{int(secondes // 60)} min"


def rapport_final(etat: dict, views=()) -> str:
    """Notes du démon, comparaison avec la base, puis le rendu compact de chaque sous-run
    (navigateur à part ; échecs regroupés par signature, sortie complète sauvée)."""
    from ..tools.ops.pytest_compact import rendu_pytest
    morceaux = [etat["notes"].rstrip()] if etat["notes"].strip() else []
    if etat.get("timed_out"):
        morceaux.append("Error: tests timed out (process killed)")
    if etat["state"] == "cancelled":
        morceaux.append("[testd] job annulé.")
    if etat.get("base"):
        morceaux.append(etat["base"].rstrip())
    parties = etat.get("parts") or []
    for partie in parties:
        sortie = Path(partie["output"]).read_text(encoding="utf-8", errors="replace").strip()
        titre = {"other": "── tests hors navigateur ──", "browser": "── tests navigateur ──"}.get(partie["label"])
        rendu = rendu_pytest(sortie or "(no output)", views, toujours_sauver=True)
        morceaux.append(f"{titre}\n{rendu}" if titre and len(parties) > 1 else rendu)
    return "\n".join(morceaux)


def sortie_brute(etat: dict) -> str:
    return "\n".join(Path(p["output"]).read_text(encoding="utf-8", errors="replace")
                     for p in etat.get("parts") or [])


def texte_etat(etat: dict, views=()) -> str:
    """Ce que TestStatus rend au modèle."""
    tete = f"[testd] job {etat['job_id']} : "
    if etat["state"] == "queued":
        return tete + ligne_avancement(etat).replace("pytest: ", "")
    if etat["state"] in ("done", "cancelled"):
        return (tete + f"terminé ({etat['elapsed_s']:.0f} s d'exécution, {etat['queued_s']:.0f} s "
                f"en file)\n" + rapport_final(etat, views))
    lignes = [tete + f"en cours depuis {etat['elapsed_s']:.0f} s — "
              + ligne_avancement({**etat, "longest": None}).replace("pytest: ", "")]
    if etat.get("longest"):
        lignes.append(f"le plus long en cours : {etat['longest']['id']} ({etat['longest']['elapsed_s']:.0f} s)")
    if etat["failures"]:
        lignes.append(f"échecs ({len(etat['failures'])}) :")
        for echec in etat["failures"][:_ECHECS_MONTRES]:
            extrait = "\n".join("    " + l for l in echec["excerpt"].splitlines()[-6:])
            lignes.append(f"✗ {echec['id']}\n{extrait}")
    return "\n".join(lignes)


def attendre(job_id: str, wait_s: float, progression=None, annule=None, au_premier_echec=True) -> dict:
    """Sonde le job jusqu'à sa fin, un nouvel échec (si `au_premier_echec`), l'expiration de
    `wait_s` ou une interruption ; pousse la ligne d'avancement à `progression`."""
    fin = time.monotonic() + wait_s
    etat = client.etat(job_id)
    echecs = len(etat.get("failures") or [])
    while etat["state"] in ("queued", "running") and time.monotonic() < fin:
        if annule is not None and annule():
            break
        time.sleep(_SONDAGE_S)
        etat = client.etat(job_id)
        if progression is not None:
            progression(ligne_avancement(etat))
        if au_premier_echec and len(etat.get("failures") or []) > echecs:
            break
    return etat


def statut_job(job_id: str, wait_s=0, cancel: bool = False, annule=None) -> str:
    """L'outil TestStatus."""
    if cancel:
        return texte_etat(client.annuler(job_id))
    attente = min(max(int(wait_s or 0), 0), MAX_ATTENTE_S)
    return texte_etat(attendre(job_id, attente, annule=annule))


def via_testd(cmd_parts: list[str], env: dict, project_root: Path, python: str, timeout: int,
              wait: bool, progression, views, entete: str, cibles=(), base: dict | None = None,
              a_nettoyer=()) -> str | None:
    """RunPythonTest par la file du démon. None : rien de fait, le chemin direct prend le relais
    (démon coupé, ou pytest absent de l'environnement : le repli `--with pytest` est local).
    `a_nettoyer` n'est confié au démon que si `wait=False` : sinon l'appelant nettoie, et peut
    encore rejouer localement."""
    if not client.demon_actif():
        return None
    job = client.soumettre(cmd_parts, env, str(project_root), timeout, python or cmd_parts[0],
                           cibles, base, () if wait else a_nettoyer)
    cmd_str = " ".join(cmd_parts)
    if not wait:
        place = f"en file, position {job['position']}" if job["position"] else "lancé"
        return (f"{entete}[RunPythonTest] job {job['job_id']} {place} "
                f"— cwd={project_root}\n$ {cmd_str}\nSuis-le avec TestStatus(job_id=\"{job['job_id']}\", "
                f"wait_s=…) : avancement, échecs dès qu'ils arrivent, rapport final.")
    terminal = None
    if progression is None:
        from ..tools.ops.progression_terminal import LigneProgression
        terminal = progression = LigneProgression()
    try:
        etat = attendre(job["job_id"], timeout + 24 * 3600, progression, au_premier_echec=False)
    except KeyboardInterrupt:
        client.annuler(job["job_id"])  # l'agent interrompu ne doit pas laisser un run orphelin
        raise
    finally:
        if terminal is not None:
            terminal.fermer()
    from ..tools.ops.test_runner import _looks_like_missing_pytest
    if _looks_like_missing_pytest(sortie_brute(etat)):
        return None
    return (f"{entete}[RunPythonTest] cwd={project_root} · testd job {job['job_id']} "
            f"({etat['queued_s']:.0f} s en file)\n$ {cmd_str}\n{'─' * 60}\n" + rapport_final(etat, views))
