# [desc] Le process d'un agent vit-il encore ? pid disparu, recyclé ou zombie (`processus_absent`). [/desc]
"""Vivacité du process d'un agent : pid disparu, pid recyclé par l'OS, zombie. Les absences
constatées sont mémorisées, jamais les présences."""
from __future__ import annotations

import sys
import threading

import psutil

from .. import warmpool
from .agent_fiche import Agent


def _instant_de_creation(pid: int) -> float:
    """Instant de création du process `pid` (epoch), 0.0 s'il est illisible ou absent."""
    try:
        return psutil.Process(pid).create_time()
    except (psutil.Error, OSError, RuntimeError):  # RuntimeError : /proc/stat illisible
        return 0.0


ZOMBIE = "zombie"


def _nom_du_process(proc) -> str:
    try:
        return proc.name() or "?"
    except (psutil.Error, OSError):
        return "?"


# Absences CONSTATÉES, par identité de process (pid, instant de création relevé au spawn).
# Une absence est définitive : un process disparu ne revient pas, un pid recyclé désigne un
# autre programme tant qu'il vit (et un nouveau spawn change le pid ou l'instant, donc la clé).
# Seule la PRÉSENCE est donc revérifiée à chaque appel. Sous Windows, chaque vérification d'un
# pid recyclé coûte une énumération de tous les process (create_time/name d'un process d'autrui
# passent par NtQuerySystemInformation) ; l'arbre des agents en faisait trois par agent et par
# requête (agent_status, is_warm, classify_agent) : 1031 appels, plusieurs secondes, mesurés
# sous Windows sur /api/inbox à froid.
_ABSENCES_MAX = 4096
_absences: dict[tuple, str] = {}
_absences_lock = threading.Lock()

# Un ZOMBIE n'existe pas sous Windows (psutil n'y rend que running/stopped), et y lire le
# statut énumère tous les process : on ne le demande pas.
_ZOMBIES_POSSIBLES = sys.platform != "win32"


def processus_absent(agent: Agent) -> str:
    """"" si le process de la fiche vit ENCORE, sinon POURQUOI il n'est plus là.

    Trois morts que `pid_exists` seul ne voyait pas toutes :
      * le pid n'existe plus ;
      * le pid existe mais désigne un AUTRE programme (recyclé par l'OS) : son instant de
        création diffère de celui relevé au spawn ;
      * le process est un ZOMBIE (fini, pas encore ramassé par son parent) : `ZOMBIE`.
    Un refus d'accès ne prouve rien : on ne déclare pas mort ce qu'on ne peut pas observer, et
    un process qui disparaît entre deux appels sera vu au relevé suivant.

    Une absence constatée est mémorisée (cf. `_absences`) ; une présence ne l'est jamais."""
    if not agent.pid:
        return "aucun processus enregistré"
    cle = (agent.pid, getattr(agent, "pid_create_time", 0.0) or 0.0)
    with _absences_lock:
        connue = _absences.get(cle)
    if connue is not None:
        return connue
    raison = _constater_l_absence(agent.pid, cle[1] or _borne_de_fin(agent))
    if raison:
        with _absences_lock:
            if len(_absences) >= _ABSENCES_MAX:
                _absences.clear()
            _absences[cle] = raison
    return raison


def _borne_de_fin(agent: Agent) -> float:
    """Fiche ANTÉRIEURE à `pid_create_time` : sa fin enregistrée, NÉGATIVE (epoch), 0.0 sinon.

    Un process créé APRÈS la fin enregistrée d'un agent n'est pas le sien : c'est son pid
    recyclé. Sans cette borne, les fiches d'avant le 2026-09-24 ne jugeaient que l'existence
    du pid, et 32 agents finis depuis juillet passaient pour chauds — le ménage du pool leur
    écrivait un `cancel.flag` à chaque tick (~1/s le 2026-09-29, ~160 dans la matinée)."""
    fin = warmpool.parse_instant(getattr(agent, "finished_at", "") or "")
    return -fin.timestamp() if fin else 0.0


def _constater_l_absence(pid: int, reference: float) -> str:
    """`reference` > 0 : instant de création relevé au spawn ; < 0 : borne de fin (cf.
    `_borne_de_fin`) — le process ne peut pas être né après elle ; 0 : rien à comparer."""
    if not psutil.pid_exists(pid):
        return f"processus disparu (pid {pid})"
    try:
        proc = psutil.Process(pid)
        if reference > 0 and abs(proc.create_time() - reference) > 1.0:
            return f"pid {pid} réutilisé par un autre programme ({_nom_du_process(proc)})"
        if reference < 0 and proc.create_time() > -reference + 1.0:
            return (f"pid {pid} réutilisé par un autre programme ({_nom_du_process(proc)}), "
                    f"né après la fin de l'agent")
        if _ZOMBIES_POSSIBLES and proc.status() == psutil.STATUS_ZOMBIE:
            return ZOMBIE
    except psutil.ZombieProcess:
        return ZOMBIE
    except (psutil.Error, OSError, RuntimeError):
        return ""
    return ""


def is_running(agent: Agent) -> bool:
    """Le process de CET agent tourne-t-il ? Un pid recyclé ou un zombie ne comptent pas."""
    return agent.returncode is None and not processus_absent(agent)
