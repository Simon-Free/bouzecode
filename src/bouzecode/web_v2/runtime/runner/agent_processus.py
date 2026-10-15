# [desc] Process d'une session retrouvés par leur ligne de commande ; preuve qu'un pid est encore celui de l'agent. [/desc]
"""Autorité OS sur les process d'un agent : ceux dont la cmdline référence sa session, et la
preuve qu'un pid tracké lui appartient encore (pas recyclé)."""
from __future__ import annotations

import time

import psutil

from .agent_fiche import Agent


def _procs_for_session(session_path: str):
    """Yield live python processes whose command line references `session_path` (unique per
    agent). Autorité disque/OS, indépendante du pid en mémoire — base du reap ET de la garde
    d'idempotence de spawn.

    Seul le NOM est demandé à `process_iter` : la cmdline n'est lue qu'une fois le process
    reconnu comme python. Demander `cmdline` à `process_iter` la lisait pour les ~1 000
    process du poste (lecture de la mémoire de CHAQUE process) : 0,3 à 1,1 s par scan à vide,
    jusqu'à 26 s pour un test sous `pytest -n 4`, contre ~0,01 s en filtrant d'abord."""
    if not session_path:
        return
    for proc in psutil.process_iter(["name"]):
        if not str(proc.info.get("name") or "").lower().startswith("python"):
            continue
        try:
            cmdline = proc.as_dict(["cmdline"], ad_value=None)["cmdline"]
        except psutil.NoSuchProcess:
            continue  # mort entre l'énumération et la lecture : il ne porte plus la session
        if any(session_path in str(arg) for arg in (cmdline or [])):
            yield proc


def _session_process_running(session_path: str) -> bool:
    """Un process est-il DÉJÀ vivant pour cette session ? (garde anti double-spawn au respawn)."""
    return any(proc.is_running() for proc in _procs_for_session(session_path))


# Alias public : c'est la SEULE preuve de vivacité qui ne dépende ni du pid tracké (recyclable)
# ni des champs `returncode`/`finished_at` du .json (écrits par un autre process, donc
# possiblement périmés). `purge` s'en sert avant de déplacer le moindre artefact.
session_process_running = _session_process_running


def _pid_still_belongs_to(agent: Agent) -> bool:
    """Le pid tracké désigne-t-il ENCORE le process de cet agent ?

    Un pid est RECYCLÉ par l'OS dès que son process meurt : le pid d'un agent terminé
    désigne, quelques heures plus tard, un process TIERS arbitraire. C'est ce qui a été
    observé — un `terminate()` refusé par les ACL Windows sur un pid qui n'appartenait
    plus à l'agent depuis longtemps. `AccessDenied` ne disait pas « le système protège
    l'agent » mais « ce pid n'est plus le sien ».

    Preuve retenue : la COMMAND LINE doit encore référencer le `--session-file` de
    l'agent (unique par agent) — la même autorité OS que `_procs_for_session`. Mesuré
    sous Windows avec psutil 7.2.2 sur ce poste :
      * `cmdline()` est LISIBLE pour nos propres agents (même utilisateur) et lève
        `AccessDenied` sur les process système/d'un autre utilisateur — c'est-à-dire
        exactement ceux qu'il ne faut JAMAIS tuer : le refus est fail-safe ;
      * `create_time()` est, lui, lisible sur TOUS les process. Il ne se compare PAS à
        `started_at` (que `_respawn` ne rafraîchit pas), mais à `agent.pid_create_time`,
        relevé à chaque spawn, respawn et adoption (cf. `processus_absent`). Un écart prouve
        que le pid a été RECYCLÉ : refus immédiat, sans lire la cmdline. Il ne suffit pas
        à prouver l'appartenance (fiche antérieure à 0.0, ACL Windows) : la cmdline reste
        la preuve positive.
    L'`exec` qui suit `Popen` ne change ni le pid ni son instant de création : pendant cette
    fenêtre la référence concorde déjà, et seule la cmdline, encore vide, est attendue
    (`_cmdline_apres_exec`).
    Sans `session_path` (agent hors spawn normal), aucune preuve n'est possible → False."""
    if not agent.session_path:
        return False
    try:
        proc = psutil.Process(agent.pid)
        reference = getattr(agent, "pid_create_time", 0.0) or 0.0
        if reference and abs(proc.create_time() - reference) > 1.0:
            return False  # pid recyclé : même seuil que `processus_absent`
        cmdline = _cmdline_apres_exec(proc)
    except (psutil.Error, OSError, RuntimeError):  # RuntimeError : /proc/stat illisible
        return False  # pid disparu, ou process d'autrui : dans les deux cas, pas le nôtre
    return any(agent.session_path in str(arg) for arg in cmdline)


pid_still_belongs_to = _pid_still_belongs_to  # alias public (preuve d'identité, warm_pool)


def _cmdline_apres_exec(proc) -> list[str]:
    """La ligne de commande de `proc`, attendue brièvement si elle est VIDE.

    Juste après `Popen`, le parent reprend la main pendant l'`exec` de l'enfant, avant que le
    noyau ait posé les arguments du nouveau programme : `/proc/<pid>/cmdline` est alors vide.
    Mesuré sous charge : 1 lecture sur 300. La preuve d'identité échouait donc sur un agent
    qu'on venait de lancer, et on refusait de l'arrêter. C'était la cause de
    test_refresh_marks_finished_when_ipc_finished (TimeoutExpired de 5 s sous -n 8), et c'est
    le cas d'un « Arrêter » reçu pendant le spawn. L'attente ne porte que sur le cas vide
    d'un process vivant, et elle est bornée."""
    for _ in range(50):
        cmdline = proc.cmdline() or []
        if cmdline or proc.status() == psutil.STATUS_ZOMBIE:
            return cmdline
        time.sleep(0.01)
    return []
