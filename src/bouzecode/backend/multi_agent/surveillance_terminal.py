# [desc] Suivi d'un sous-agent lancé en fenêtre de terminal : un thread relève son résultat, sa fiche de clôture ou sa mort (PID), et tient `task.status` à jour ; arrêt par PID. [/desc]
"""Les lanceurs (wt.exe, `cmd /c start`) rendent la main tout de suite : le parent ne tient
aucun handle sur l'enfant. Avant ce module, un enfant lancé en arrière-plan restait « running »
pour toujours (rien ne relisait son fichier résultat), `CheckAgentResult(wait=true)` rendait la
main aussitôt (pas de `_future`) et `Environment(integrate)` était refusé sans fin — session
9d81964e du 2026-10-06. L'enfant écrit son PID (`<stem>.pid`) au démarrage : le parent sait
s'il vit encore et peut l'arrêter."""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import Future
from pathlib import Path

from .resultat_terminal import constat

_INTERVALLE_S = 2.0
#  Un enfant en terminal peut travailler longtemps ; au-delà, le suivi abandonne (l'enfant,
#  s'il vit encore, reste arrêtable par son PID).
_PLAFOND_S = 6 * 3600.0
_ACTIFS = frozenset({"pending", "running"})
#  L'enfant écrit son PID dès le parsing de ses arguments (quelques secondes). Sans PID passé
#  ce délai, le lancement a raté (onglet jamais ouvert, crash à l'import) : sans ce délai, le
#  suivi attendrait le plafond, puisqu'il n'a aucun process à déclarer mort. Large (60 s, pour
#  ~30 s demandés) : un faux « raté » sur une machine chargée orphelinerait un enfant vivant.
_DELAI_SIGNE_DE_VIE_S = 60.0


def chemin_pid(result_file: str | Path) -> Path:
    chemin = Path(result_file)
    return chemin.with_name(chemin.stem + ".pid")


def ecrire_pid(result_file: str) -> None:
    """Appelé par l'enfant (`--result-file`) dès son démarrage."""
    chemin_pid(result_file).write_text(str(os.getpid()), encoding="utf-8")


def pid_de_l_enfant(result_file: str) -> int | None:
    chemin = chemin_pid(result_file)
    texte = chemin.read_text(encoding="utf-8").strip() if chemin.exists() else ""
    return int(texte) if texte.isdigit() else None


def _process_vivant(pid: int):
    """Le `psutil.Process` de l'enfant s'il vit encore, sinon None. L'enfant peut mourir
    ENTRE deux appels psutil (`pid_exists` vrai, puis `status()` lève NoSuchProcess) : cette
    mort-là est la réponse attendue, pas une erreur — avant, l'exception tuait le thread de
    suivi et la tâche restait « running » pour toujours (1 run sur 3 sous charge)."""
    import psutil
    try:
        process = psutil.Process(pid)
        return None if process.status() == psutil.STATUS_ZOMBIE else process
    except psutil.NoSuchProcess:
        return None


def _vivant(pid: int) -> bool:
    return _process_vivant(pid) is not None


def releve(result_file: str) -> tuple[str, str] | None:
    """Résultat, fiche, ou mort de l'enfant sans l'un ni l'autre ; None s'il travaille encore."""
    trouve = constat(result_file)
    if trouve is not None:
        return trouve
    pid = pid_de_l_enfant(result_file)
    if pid is None or _vivant(pid):
        return None
    #  Mort entre deux relevés : ses fichiers ont pu être écrits juste avant.
    return constat(result_file) or (
        "failed", f"Sub-agent process {pid} died without a result or a close fiche.")


def _suivre(task, result_file: str, future: Future, intervalle_s: float,
            plafond_s: float, delai_signe_de_vie_s: float) -> None:
    try:
        _relever_jusqu_a_la_fin(task, result_file, intervalle_s, plafond_s, delai_signe_de_vie_s)
    except Exception as erreur:
        #  Le suivi lui-même a planté : la tâche ne doit pas rester « running » sans personne
        #  pour la faire avancer. L'erreur devient son résultat, que lit CheckAgentResult (un
        #  `raise` ici ne finirait que dans le excepthook d'un thread démon, que nul ne lit).
        task.status, task.result = "failed", f"Sub-agent follow-up crashed: {erreur!r}"
    finally:
        future.set_result(task.status)


def _relever_jusqu_a_la_fin(task, result_file: str, intervalle_s: float, plafond_s: float,
                            delai_signe_de_vie_s: float) -> None:
    debut = time.monotonic()
    while task.status in _ACTIFS:
        trouve = releve(result_file)
        ecoule = time.monotonic() - debut
        if (trouve is None and ecoule >= delai_signe_de_vie_s
                and pid_de_l_enfant(result_file) is None):
            trouve = ("failed", f"No sign of life from the sub-agent after {int(ecoule)}s "
                                "(PID never written): the launch failed.")
        if trouve is None and ecoule >= plafond_s:
            trouve = ("failed", f"Sub-agent still silent after {int(plafond_s)}s: no longer "
                                "followed (stop it with CheckAgentResult(arreter=true)).")
        if trouve is not None:
            task.status, task.result = trouve
            break
        time.sleep(intervalle_s)


def surveiller(task, result_file: str, intervalle_s: float = _INTERVALLE_S,
               plafond_s: float = _PLAFOND_S,
               delai_signe_de_vie_s: float = _DELAI_SIGNE_DE_VIE_S) -> Future:
    """Pose `task._future` et lance le thread de suivi (démon : ne retient pas la sortie)."""
    future: Future = Future()
    task._future = future
    task.result_file = result_file
    threading.Thread(target=_suivre, args=(task, result_file, future, intervalle_s, plafond_s,
                                           delai_signe_de_vie_s),
                     name=f"suivi-enfant-{task.id}", daemon=True).start()
    return future


def arreter(task) -> str:
    """Tue l'arbre de process de l'enfant (PID écrit au démarrage) et le marque `cancelled`."""
    import psutil
    result_file = getattr(task, "result_file", "") or ""
    pid = pid_de_l_enfant(result_file) if result_file else None
    racine = _process_vivant(pid) if pid is not None else None
    if racine is None:
        task.status = "cancelled"
        return f"{task.id} : aucun process vivant connu (PID {pid or 'non écrit'}) ; marqué arrêté."
    process = [*racine.children(recursive=True), racine]
    for un_process in process:
        try:
            un_process.kill()
        except psutil.NoSuchProcess:
            pass  # déjà sorti entre l'inventaire et le kill : c'est le but
    psutil.wait_procs(process, timeout=10)
    task.status, task.result = "cancelled", f"Arrêté par le parent (PID {pid})."
    return f"{task.id} arrêté (PID {pid}, {len(process)} process)."
