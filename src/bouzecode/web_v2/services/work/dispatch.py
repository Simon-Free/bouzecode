# [desc] Lancement de l'agent d'un ticket déjà créé : profil (défaut `coder` d'un manager), spawn synchrone ou en fond, échec gravé sur le ticket, arrêt d'une préparation. [/desc]
"""Le ticket est créé par `api_tickets/creation.py` (POST /api/projects/{slug}/tickets, seul
chemin de création : le projet est TOUJOURS explicite, plus aucun routage par intention depuis
le lot L6) ; ce module lance son agent (`_launch`, `_launch_bg`) et grave l'échec d'un
lancement (`record_launch_failure`)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ...runtime.runner import agent_commande, agent_creation
from ..typologies import get_typology
from . import launch_phase, repos, ticket_fsm, tickets
from .fsm import etats
from .isolation import SHARED, WORKTREE  # noqa: F401 — ré-export (appelants : dispatch.SHARED)
# Façade : le PROVISIONNEMENT (worktree, venv, ré-isolation, re-logement) vit dans
# `provisioning.py`. Ré-exporté ici pour que les appelants gardent `dispatch.reisolate` /
# `dispatch.rehome_agent_cwd` — ce module décide OÙ et QUOI lancer, il ne creuse plus lui-même.
from .provisioning import (  # noqa: F401 — ré-export façade
    _is_live_worktree,
    _path_of,
    _provision_worktree,
    _report_venv_issue,
    rehome_agent_cwd,
    reisolate,
)

# Une seule définition, au plus bas niveau (`agent_commande`), parce que c'est `_ticket_env` qui
# décide si cette sentinelle part dans l'env du process — et l'y envoyer éteignait le warm-pool
# des conversations utilisateur.
_MANUAL_PARENT = agent_commande.MANUAL_PARENT


_CODER_PROFILE = "coder"

_log = logging.getLogger(__name__)


def is_managed_parent(parent: str) -> bool:
    """Un lancement est MANAGÉ quand son `parent` est un vrai agent_id de manager.

    Pas de parent (création/relance manuelle depuis l'UI) ou le sentinelle
    `dispatcher:manual` → NON managé. C'est la seule lecture autorisée de `parent`
    pour `resolve_profile(managed=...)` : sans elle, un appelant qui omet `managed=`
    hérite du défaut `True` et pousse silencieusement TOUT ticket web sur `coder`."""
    parent = (parent or "").strip()
    return bool(parent) and parent != _MANUAL_PARENT


#  Posé sur un ticket RATTACHÉ à un agent qui ne le manage pas (l'assistant du Bureau : il est
#  prévenu des fins et des questions, mais la tâche garde le profil d'un lancement depuis
#  l'écran). Sans cette trace, le parent agent faisait lire le ticket comme MANAGÉ à sa relance
#  (`est_manage`) et le défaut `coder` s'appliquait.
NON_MANAGE = "non_manage"


def est_manage(ticket: dict) -> bool:
    """Le ticket a-t-il été lancé MANAGÉ ? Lecture de `managed` pour une RELANCE : un parent
    agent suffit, sauf si le ticket lui a été rattaché sans être managé (`NON_MANAGE`)."""
    return not ticket.get(NON_MANAGE) and is_managed_parent(ticket.get("parent") or "")


def resolve_profile(typology_name: str, project_path: str, managed: bool = True) -> str:
    """Résout typology → profile en appliquant un DÉFAUT CODEUR sur les projets de code.

    Règle : si une typology explicite (autre que "default") est fournie, on la RESPECTE
    telle quelle (y compris manager/monitor, profile éventuellement vide). Mais si AUCUN
    profil codeur n'est déterminé (typology absente ou "default", donc profile vide) ET
    que le projet est un dépôt git (= projet de CODE), on applique le profil codeur par
    défaut `coder` — sinon l'agent partait NU (pas de RunPythonTest, pas de skill
    demo-coding, pas de format de livraison → churn massif). Projet non-code → "" (pas
    de régression : agent standard comme avant).

    `managed` : le DÉFAUT codeur ne s'applique QUE quand le lancement est MANAGÉ, c.-à-d.
    spawné par un manager (parent = agent_id). Un lancement DIRECT depuis l'UI
    (parent = "dispatcher:manual", managed=False) avec une typology absente/"default" reste
    un agent NU — identique à la TUI. Le profil ne décide PLUS de l'isolation : celle-ci
    est demandée explicitement au dispatch (cf. `resolve_isolation`)."""
    typo = get_typology(typology_name, project_path) if typology_name else None
    profile = typo["profile"] if typo else ""
    if profile == "" and (typology_name or "").strip().lower() in ("", "default"):
        if managed and repos.repo_root(project_path):
            _log.info("typology absente, défaut coder appliqué (managé, projet=%s)", project_path)
            return _CODER_PROFILE
    return profile


def base_venv_for(isolation: str, project_path: str) -> str:
    """Venv que l'agent doit UTILISER, ou "" s'il n'a pas à en emprunter un.

    C'est la traduction directe du contrat d'isolation choisi par le manager (paramètre
    `isolation` de l'outil `Agent`) — aucune option nouvelle, aucune déduction :

    | isolation       | environnement Python de l'agent                                   |
    |-----------------|-------------------------------------------------------------------|
    | `shared`        | celui du dépôt : son cwd EST le dépôt, rien à faire ("")           |
    | `worktree`      | **celui du dépôt de base, emprunté** — c'est ce qu'on renvoie ici  |
    | `worktree+venv` | le sien, provisionné dans son worktree ("")                       |

    POURQUOI. Un worktree sans venv laissait l'agent sans aucun environnement, et `uv` en
    fabriquait un dans le worktree au premier `uv run` : ~1 Go que personne n'avait demandé
    (mesuré : 11 des 21 tickets `worktree` en portaient un). Le venv est cherché à la RACINE DU
    DÉPÔT, pas au chemin du projet : un projet peut pointer un sous-dossier du dépôt."""
    if isolation != WORKTREE:
        return ""
    root = repos.repo_root(project_path) or project_path
    return str(Path(root) / ".venv")


def _launch(slug: str, ticket: dict, project_path: str, profile: str, model: str,
            isolation: str = SHARED, parent: str = "", resume_branch: str = "",
            work_branch: str = ""):
    """Partie LOURDE du dispatch : provisionne le worktree (et le venv seulement si
    `isolation == 'worktree+venv'`), spawn l'agent, enregistre son run 'work'."""
    cwd = (_provision_worktree(slug, ticket, project_path, resume_branch, isolation, work_branch)
           if isolation != SHARED else project_path)
    worktree_root = ""
    if cwd != project_path:
        # Prompt du ticket INTACT. Le contrat « worktree isolé » vit dans le SYSTEM prompt
        # de l'agent (context.py, via l'env BOUZECODE_WORKTREE_ROOT armée au spawn).
        worktree_root = cwd
    # `create_agent` monte l'environnement du provider puis Popen : quelques secondes, mais
    # c'est la dernière étape avant l'apparition du run, donc la seule qui reste à nommer
    # pour que l'attente n'ait plus AUCUN trou. `add_run` retire la phase juste après.
    if _arret_demande(tickets.get_ticket(slug, ticket["id"]) or {}):
        raise LancementArrete(ticket["id"])  # arrêté pendant le worktree : rien ne démarre
    launch_phase.set_phase(slug, ticket, launch_phase.SPAWNING)
    agent = agent_creation.create_agent(ticket["prompt"], model, cwd, profile=profile,
                                parent=parent, ticket_slug=slug, ticket_id=ticket["id"],
                                worktree_root=worktree_root,
                                base_venv=base_venv_for(isolation, project_path))
    arret = tickets.add_run(slug, ticket, agent.agent_id, "work", model,
                            typology=ticket.get("typology", ""))
    if arret:
        # Arrêt demandé pendant le spawn : le run est inscrit terminé (la tâche montre l'agent
        # arrêté, comme un arrêt reçu une seconde plus tard), puis l'agent est arrêté aussitôt.
        from .taches_actions import _tuer
        _tuer(agent.agent_id)
    return agent


class LancementArrete(RuntimeError):
    """L'utilisateur a arrêté la tâche pendant la préparation : aucun agent ne doit démarrer."""


def _arret_demande(ticket: dict) -> bool:
    """L'utilisateur a arrêté la tâche pendant sa préparation (`stopped{arret_preparation}`)."""
    from . import etat_ticket
    from .runs_ticket import ARRET_PREPARATION
    return (ticket.get("state") == etats.STOPPED
            and etat_ticket.code_raison(ticket) == ARRET_PREPARATION)


def arreter_la_preparation(slug: str, ticket: dict) -> str:
    """« Arrêter » sur un lancement en préparation.

    Si l'agent a déjà son run, son agent_id est rendu pour que l'appelant l'arrête. Sinon le
    ticket passe `stopped{arret_preparation}` (transition sous verrou) : `_launch` le relit
    avant le spawn, et `add_run` inscrit terminé le run d'un agent né entre-temps."""
    from .lexique import ERREUR_ARRET_PREPARATION
    from .runs_ticket import ARRET_PREPARATION
    frais = tickets.get_ticket(slug, ticket["id"]) or ticket
    runs = [r for r in frais.get("runs") or [] if isinstance(r, dict) and r.get("agent_id")]
    if runs and frais.get("state") != etats.PROVISIONING:
        return str(runs[0]["agent_id"])
    if frais.get("state") == etats.PROVISIONING:
        ticket_fsm.appliquer(slug, ticket["id"], etats.STOP, "utilisateur",
                             code=ARRET_PREPARATION, message=ERREUR_ARRET_PREPARATION)
        tickets.add_comment(slug, ticket, f"⚠️ Lancement arrêté : {ERREUR_ARRET_PREPARATION}", True)
    return ""


def record_launch_failure(slug: str, ticket: dict, error: str) -> None:
    """Grave l'échec de lancement : `provisioning` → `launch_failed{lancement_echoue}`, le motif
    dans `state_reason.message`. Un enfant mort-né est ainsi une ISSUE pour le réveil de son
    parent (`wake.launch_failed`), et le manager ne peut pas se clore « terminé » par-dessus.
    Un ticket qui n'est plus en préparation (arrêté entre-temps) garde son état : seul le
    motif est consigné."""
    frais = tickets.get_ticket(slug, ticket["id"])
    if frais is not None and frais.get("state") == etats.PROVISIONING:
        frais = ticket_fsm.appliquer(slug, ticket["id"], etats.LAUNCH_FAILED_EVENT, "serveur",
                                     code="lancement_echoue", message=str(error)[:500])
        ticket.clear()
        ticket.update(frais)
    tickets.add_comment(slug, ticket, f"⚠️ Lancement échoué : {error}", True)


def _launch_bg(*args: Any) -> None:
    """Wrapper tâche de fond : une exception (env provider manquant, git KO) est LOGGÉE,
    jamais avalée en silence, et ne tue pas le process serveur."""
    try:
        _launch(*args)
    except LancementArrete as arret:
        logging.getLogger(__name__).info("lancement du ticket %s arrêté pendant la préparation", arret)
    except Exception as exc:  # noqa: BLE001 — thread daemon : logguer, ne pas planter le serveur
        slug = args[0] if args and isinstance(args[0], str) else ""
        ticket = args[1] if len(args) > 1 and isinstance(args[1], dict) else {}
        tid = ticket.get("id", "?")
        logging.getLogger(__name__).exception("dispatch._launch_bg a échoué (ticket %s)", tid)
        # Échec de lancement en fond : rendre l'erreur VISIBLE sur le ticket (jamais avalée) et
        # poser l'issue TERMINALE EN ÉCHEC (`launch_failed`) qui réveille le manager parent.
        if slug and ticket.get("id"):
            record_launch_failure(slug, ticket, str(exc))
