# [desc] Arrêt d'un agent : kill, cancel doux, reap des jumeaux, garde `destruction_permitted`. [/desc]
"""Arrêter un agent : `kill_agent` (cancel.flag + terminate + reap des jumeaux de session),
`graceful_cancel_agent`, et les gardes qui empêchent de tuer un pid qui n'est plus le sien."""
from __future__ import annotations

import logging
import os

import psutil

from .. import ipc
from .. import kill_journal
from .. import pending as web_pending
from . import agent_fiche
from . import agent_vivacite
from . import agent_processus
from . import agent_etat
from . import agent_chaud
from .agent_fiche import Agent


def _moi_et_mes_ancetres() -> set[int]:
    """Pids du process courant et de ses ancêtres. L'intégration tourne DANS le process de
    l'agent (outil Environment) : le reap d'après-merge le visait lui-même, et l'agent mourait
    en plein appel d'outil (SIGTERM) sans pouvoir rendre sa réponse finale."""
    pids = {os.getpid()}
    try:
        pids.update(p.pid for p in psutil.Process().parents())
    except psutil.Error:
        pass  # sans ancêtres connus on épargne au moins soi-même
    return pids


def reap_session_processes(session_path: str) -> int:
    """Terminate every python process whose command line references `session_path`.

    A double-spawn leaves an untracked TWIN process (same ``--session-file``) that
    `kill_agent` — which knows only the last tracked pid — cannot reach; it keeps looping
    and burning tokens after the ticket merged. Called on integration to reap the twin.
    Matching on the (unique per agent) session-file path never touches an unrelated
    process. Returns the number of processes terminated."""
    killed = 0
    epargnes = _moi_et_mes_ancetres()
    for proc in agent_processus._procs_for_session(session_path):
        if proc.pid in epargnes:
            continue  # l'agent qui intègre lui-même : le tuer l'empêchait de rendre sa réponse
        if proc.is_running() and not signal_termination(proc):
            continue  # refus de l'OS sur CE process : les jumeaux suivants y ont droit
        killed += 1
    return killed


def signal_termination(proc, agent: "Agent | None" = None) -> bool:
    """Envoie `terminate()` et fait du REFUS DE L'OS un résultat, jamais une panne.

    `psutil.AccessDenied` sur un pid est un cas COURANT sous Windows : process en train de
    mourir, pid recyclé par un process d'une autre session, ACL. Il remontait jusqu'ici tel
    quel — donc jusqu'à `refresh_agent_status`, appelé par CHAQUE `list_agents()`, c'est-à-dire
    par presque toutes les routes : un seul pid intouchable et le serveur entier répondait 500
    (incident du 28/07, trois /interrupt d'affilée).

    Rien n'est avalé : le motif est journalisé ET inscrit sur l'agent (`termination_error`,
    servi par l'API), et remis à "" dès qu'une terminaison aboutit."""
    try:
        proc.terminate()
    except (psutil.Error, OSError) as exc:
        motif = f"{type(exc).__name__} (pid={getattr(proc, 'pid', '?')})"
        logging.getLogger(__name__).warning(
            "terminaison refusée par l'OS : %s — l'agent reste vivant", motif)
        if agent is not None:
            agent.termination_error = motif
            agent_fiche._save(agent)
        return False
    if agent is not None and agent.termination_error:
        agent.termination_error = ""
        agent_fiche._save(agent)
    return True


def destruction_permitted() -> bool:
    """False sous pytest : aucun test ne doit pouvoir DÉTRUIRE quoi que ce soit.

    Couvre les deux gestes irréversibles du serveur : terminer un process
    (`terminate_agent_process`, `fleet.sweep_warm_pool`) et déplacer les artefacts d'un
    agent hors du parc (`purge.purge_agents`). Les deux ont frappé de la production
    réelle le 2026-07-28 depuis la suite de tests.

    Détecter l'environnement de test depuis du code de production est un compromis
    assumé. Il est le bon ICI, et seulement ici, pour quatre raisons mesurées :
      * la protection concurrente (isoler le parc dans les conftests) est de la
        DISCIPLINE — et c'est précisément elle qui a cédé : l'opt-out existait déjà
        (`BOUZECODE_WAKE_POLLER`) mais le conftest posait un AUTRE nom, si bien que le
        poller tournait quand même et envoyait des centaines de `terminate()` ;
      * la discipline a cédé une SECONDE fois, et plus gravement : avant le 2026-07-28
        14:16, aucun conftest ne redirigeait `AGENTS_DIR`, `TRASH_DIR` ni `DELETED_PATH`.
        Le registre de production en porte encore la trace — quatre agents de FIXTURE
        (`parent`, `child1`, `child2`, `cccccc`) écrits dedans par la suite ;
      * le garde est UNIDIRECTIONNEL : il ne peut que REFUSER une destruction, jamais en
        provoquer une. Son pire coût en production est une éviction ou une purge manquée ;
      * `PYTEST_CURRENT_TEST` est posé par pytest LUI-MÊME dans le process qui exécute
        le test. Le serveur web_v2 est lancé par `bouzeui.ps1`, jamais par pytest : il
        n'existe pas de faux positif réaliste en exploitation.
    Le garde reste par ailleurs une couture : un test peut le neutraliser explicitement
    quand il veut prouver le comportement réel (`autoriser_la_destruction`)."""
    return "PYTEST_CURRENT_TEST" not in os.environ


def terminate_agent_process(agent: Agent) -> bool:
    """UNIQUE porte vers `terminate()` sur `agent.pid`. True ssi le signal a été envoyé.

    Ne lève jamais : un échec d'identité n'est pas une erreur d'appelant, c'est le
    fonctionnement normal du garde. Il est tracé, jamais avalé en silence."""
    if not destruction_permitted():
        return False
    if agent.returncode is not None or agent.finished_at:
        # Agent DÉJÀ terminé : son pid est libre depuis longtemps et a pu être recyclé.
        # Il n'est candidat à aucune terminaison, quelle que soit la politique appelante.
        return False
    if not agent.pid or not psutil.pid_exists(agent.pid):
        return False
    if not agent_processus._pid_still_belongs_to(agent):
        logging.getLogger(__name__).warning(
            "terminate refusé : le pid %s n'appartient plus à l'agent %s (pid recyclé)",
            agent.pid, agent.agent_id)
        return False
    return signal_termination(psutil.Process(agent.pid), agent)


def kill_agent(agent: Agent) -> dict:
    """Tue l'agent et REND COMPTE : `{signalled, error, twins}`.

    `error` n'est renseigné que sur un REFUS de l'OS (le seul cas où l'agent est toujours
    là alors qu'on a demandé son arrêt) ; `signalled=False` avec `error` vide veut dire
    qu'il n'y avait rien à tuer (déjà fini, pid recyclé, terminaison interdite sous pytest).
    L'appelant peut ainsi dire la vérité à l'utilisateur au lieu de prétendre un succès."""
    cancel_ecrit = bool(agent.ipc_dir)
    if cancel_ecrit:
        paths = ipc.from_dir(agent.ipc_dir)
        paths.cancel.write_text("", encoding="utf-8")
    signalled = terminate_agent_process(agent)
    # kill_agent ne connaît que le DERNIER pid tracké ; un twin double-spawn (même
    # --session-file, autre pid) survivrait. reap_session_processes le rattrape via
    # l'autorité OS (cmdline). session_path vide → reap renvoie 0 (no-op sûr).
    session_path = getattr(agent, "session_path", None)
    twins = reap_session_processes(session_path) if session_path else 0
    agent_etat.refresh_agent_status(agent)
    # Un agent qu'on arrête n'attend plus de réponse : son marqueur de question pendante
    # doit partir AVEC lui, sinon il continue d'annoncer une attente que personne n'honorera
    # (cas vécu : `63cd2c4183e8`, tué, listé « attend une réponse » le lendemain).
    # `pending.cancel` est le geste JUSTE — il injecte un `(cancelled by user)` pour les
    # tool_calls restés sans résultat, donc la session demeure valide pour l'API, là où un
    # simple effacement la laisserait avec un tool_call orphelin. Seulement si l'agent est
    # bien arrêté : tant qu'il respire, sa pause lui appartient.
    if session_path and not agent_vivacite.is_running(agent):
        web_pending.cancel(session_path)
    issue = {"signalled": signalled, "twins": twins,
             "error": getattr(agent, "termination_error", "") or ""}
    kill_journal.journaliser("kill", agent, cancel_ecrit=cancel_ecrit, **issue)
    if not issue["error"] and not agent_vivacite.is_running(agent):
        agent_chaud._signaler_au_ticket(agent, "arret")
    return issue


def graceful_cancel_agent(agent: Agent) -> None:
    """Write cancel.flag WITHOUT terminating — gives the subprocess time to save."""
    if agent.ipc_dir:
        paths = ipc.from_dir(agent.ipc_dir)
        paths.cancel.write_text("", encoding="utf-8")
        kill_journal.journaliser("cancel_doux", agent, cancel_ecrit=True)
