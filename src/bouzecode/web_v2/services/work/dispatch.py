# [desc] Dispatch : un prompt + un projet CHOISI → ticket + agent, avec l'isolation DEMANDÉE par le manager. [/desc]
"""Point d'entrée unique du manager : on donne un prompt, le projet, et l'isolation voulue.
`resolve_routing` (pur, sans LLM) décide titre/typologie/modèle ; `resolve_isolation` (pur)
normalise le besoin d'environnement ; `dispatch` exécute (ticket + spawn).
Sans projet choisi → needs_project."""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

from ...runtime import runner
from ..typologies import get_typology
from . import existing_branch, launch_phase, projects, repos, tickets
from .isolation import ISOLATION_MODES, SHARED, WORKTREE, resolve_isolation  # noqa: F401
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

# Une seule définition, au plus bas niveau (`runner`), parce que c'est `runner._ticket_env` qui
# décide si cette sentinelle part dans l'env du process — et l'y envoyer éteignait le warm-pool
# des conversations utilisateur.
_MANUAL_PARENT = runner.MANUAL_PARENT


def _resolve_model(typology_name: str, project_path: str | None, override: str) -> str:
    if override:
        return override
    typo = get_typology(typology_name, project_path) if typology_name else None
    return typo.get("default_model", "") if typo else ""


def resolve_routing(
    prompt: str,
    project_list: list[dict[str, Any]],
    project_slug: str = "",
    typology: str = "",
    model: str = "",
) -> dict[str, Any]:
    """Décide où router le prompt à partir du projet CHOISI par l'appelant — aucune
    déduction LLM. Le titre du ticket est la première ligne du prompt. Sans effet de bord.
    Renvoie {title, project_slug, typology, model, needs_project}."""
    title = prompt.split("\n")[0][:80].strip()
    chosen_typo = typology or "default"

    if not project_slug:
        return {"title": title, "project_slug": "", "typology": chosen_typo,
                "model": model, "needs_project": True}

    chosen_path = _path_of(project_slug, project_list)
    return {
        "title": title,
        "project_slug": project_slug,
        "typology": chosen_typo,
        "model": _resolve_model(chosen_typo, chosen_path, model),
        "needs_project": False,
    }


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


def resolve_profile(typology_name: str, project_path: str, managed: bool = True) -> str:
    """Résout typology → profile en appliquant un DÉFAUT CODEUR sur les projets de code.

    Règle : si une typology explicite (autre que "default") est fournie, on la RESPECTE
    telle quelle (y compris manager/monitor, profile éventuellement vide). Mais si AUCUN
    profil codeur n'est déterminé (typology absente ou "default", donc profile vide) ET
    que le projet est un dépôt git (= projet de CODE), on applique le profil codeur par
    défaut `coder` — sinon l'agent partait NU (pas de RunPythonTest, pas de skill
    python-coding, pas de format de livraison → churn massif). Projet non-code → "" (pas
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


def dispatch(
    prompt: str,
    project_slug: str = "",
    typology: str = "",
    model: str = "",
    parent: str = _MANUAL_PARENT,
    isolation: str = SHARED,
    defer: bool = False,
    ephemeral: bool = False,
    resume_branch: str = "",
    use_readme: bool = False,
    work_branch: str = "",
) -> dict[str, Any]:
    """Route le prompt puis crée le ticket et lance l'agent. Renvoie la décision
    enrichie de {routed, ticket_id, key, project_name} ou {needs_project, suggestions}.

    `isolation` : 'shared' (défaut, rien de provisionné), 'worktree' (worktree git seul,
    SANS venv) ou 'worktree+venv'. C'est le manager (ou l'humain) qui décide — cf.
    `isolation.resolve_isolation` pour la normalisation et le garde-fou anti-collision.

    defer=True : le travail LOURD (worktree + spawn, > 30 s) part en fond ; on répond dès
    le ticket créé (sans 'key') pour qu'un appelant à court timeout ne redispatche pas.
    ephemeral=True : ticket de TEST — travaille dans un worktree jetable, jamais mergé.
    resume_branch : point de DÉPART — le worktree est créé DEPUIS cette branche, sur une
    branche neuve `agent/<ticket>`. La livraison n'atterrit PAS sur `resume_branch`.
    work_branch : l'agent travaille SUR cette branche existante (elle est sortie telle quelle
    dans son worktree, ses commits y vont directement). Refusé BRUYAMMENT — aucun ticket, aucun
    agent — si la branche n'existe pas ou est déjà sortie ailleurs : c'est la seule alternative
    honnête au repli silencieux sur une branche neuve qui rendait la livraison invisible."""
    # HÉRITAGE DU PROJET. Un enfant dispatché PAR UN MANAGER (parent = agent_id) travaille
    # sur le projet de son manager. Sans cet héritage, l'outil `Agent` — qui n'a aucun moyen
    # de connaître le slug depuis le process de l'agent — recevait `needs_project` à TOUS les
    # coups : zéro enfant créé, manager parqué « en attente des enfants » à vie.
    # La déduction vit ICI (service) et non dans l'outil, car seul le serveur possède le
    # registre des projets + le store des agents ; l'outil, lui, ne dialogue qu'en HTTP
    # (écrivain unique). Elle profite ainsi à TOUT appelant de /api/dispatch qui fournit un
    # parent. Un `project_slug` explicite PRIME toujours (UI manuelle, override de l'outil),
    # et un lancement manuel ('dispatcher:manual') n'hérite de rien → `needs_project` intact.
    if not project_slug:
        project_slug = projects.slug_of_agent(parent)
    project_list = projects.list_projects()
    decision = resolve_routing(prompt, project_list, project_slug, typology, model)

    if decision["needs_project"]:
        decision["routed"] = False
        # Un parent MANAGÉ que le serveur ne connaît PLUS (son enregistrement d'agent a
        # disparu du store — purge, archivage, nettoyage manuel) perd son héritage de projet
        # et retombe ici. On le DIT, au lieu de laisser l'appelant lire « aucun projet
        # ouvert » et chercher un problème de configuration : ce qui a disparu, c'est SON
        # existence côté serveur, sous lui, pendant qu'il tournait (observé le 2026-07-28,
        # dossier d'un manager vivant déplacé dans web_agents/_trash).
        decision["parent_unknown"] = bool(
            is_managed_parent(parent) and runner.load_agent(parent) is None)
        decision["suggestions"] = [
            {"slug": p["slug"], "name": p["name"]} for p in project_list
        ]
        return decision

    slug = decision["project_slug"]
    project = projects.find(slug)

    # PRÉ-VOL de `work_branch`, AVANT toute création de ticket : une branche demandée qui
    # n'existe pas, ou qu'un autre worktree a déjà sortie, doit REFUSER le dispatch en nommant
    # l'occupant. Refuser ici (et non au provisioning) rend l'échec immédiat et actionnable
    # pour l'appelant — le manager reçoit une erreur d'outil au lieu d'un enfant lancé
    # ailleurs, et aucun ticket fantôme ne reste derrière.
    if work_branch:
        root = repos.repo_root(project["path"])
        blocked = (existing_branch.unavailable_reason(root, work_branch) if root else
                   f"{project['path']} n'est pas un dépôt git : `work_branch` impossible")
        if blocked:
            decision["routed"] = False
            decision["error"] = blocked
            return decision

    profile = resolve_profile(decision["typology"], project["path"],
                              managed=is_managed_parent(parent))
    # Un éphémère, un resume et un travail sur branche existante EXIGENT un worktree (bac à
    # sable jetable / départ d'une branche / checkout dédié) : contrainte structurelle, pas
    # une décision d'isolation.
    mode, reason, collision_note = resolve_isolation(
        project["path"], isolation,
        needs_worktree=bool(ephemeral or resume_branch or work_branch))

    ticket = tickets.create_ticket(slug, decision["title"], prompt)
    ticket["parent"] = parent  # réveil du manager parent quand tous ses enfants finissent
    ticket["typology"] = decision["typology"]
    ticket["isolation"] = mode
    if ephemeral:
        ticket["ephemeral"] = True  # → jamais mergé, bac à sable auto-reapé
    ticket["use_readme"] = bool(use_readme)  # case UI : trace l'autorisation README.md
    tickets.update_ticket(slug, ticket)
    if collision_note:
        tickets.add_comment(slug, ticket, collision_note, True)
        # Le manager ne lit NI les tickets NI les commentaires : son seul canal est le
        # tool_result de son appel `Agent`, qui relaie `scope_warnings`. Sans ce report,
        # une correction d'isolation décidée par le serveur ne lui parvient jamais.
        decision.setdefault("scope_warnings", []).append(collision_note)
    # GARANTIE FORTE DE TERMINALITÉ : pose `launching` SYNCHRONE avant tout retour au parent.
    # En mode defer=True, `_launch_bg` (add_run) tourne dans un thread ; entre create_ticket et
    # add_run le ticket enfant n'aurait NI launching NI run → child_pending_launch()=False ET
    # has_launched()=False → should_wake_parent() finaliserait le parent à tort.
    # add_run retire ce flag au succès ; _launch_bg le retire en cas d'échec de lancement.
    tickets.set_launching(slug, ticket)

    decision["routed"] = True
    decision["project_name"] = project["name"]
    decision["ticket_id"] = ticket["id"]
    decision["isolation"] = mode
    decision["isolation_reason"] = reason

    launch_args = (slug, ticket, project["path"], profile, decision["model"],
                   mode, parent, resume_branch, work_branch)
    if defer:
        threading.Thread(target=_launch_bg, args=launch_args, daemon=True).start()
        decision["deferred"] = True
        return decision

    agent = _launch(*launch_args)
    decision["key"] = f"agent/{agent.agent_id}"
    decision["isolated"] = "worktree" in ticket
    return decision


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
    launch_phase.set_phase(slug, ticket, launch_phase.SPAWNING)
    agent = runner.create_agent(ticket["prompt"], model, cwd, profile=profile,
                                parent=parent, ticket_slug=slug, ticket_id=ticket["id"],
                                worktree_root=worktree_root,
                                base_venv=base_venv_for(isolation, project_path))
    tickets.add_run(slug, ticket, agent.agent_id, "work", model,
                    typology=ticket.get("typology", ""))
    return agent


LAUNCH_FAILED_KEY = "launch_failed"


def record_launch_failure(slug: str, ticket: dict, error: str) -> None:
    """Grave l'échec de lancement SUR le ticket, en UNE mutation : retire l'état transitoire
    `launching` (aucun run ne viendra) et pose `launch_failed` = {error, at}.

    Sans ce drapeau PERSISTANT, un enfant dont le provisionnement échoue se présente comme un
    ticket ordinaire « à faire » (aucun run, aucun worktree, `done=False`) et n'EXISTE PAS pour
    le réveil du parent : `wake.has_launched` le compte comme un orphelin jamais lancé, donc
    `should_wake_parent` n'a « aucun enfant réel » et ne réveille personne. Le manager qui avait
    clos son tour en attendant le verdict de cet enfant attend alors indéfiniment (cas mesuré
    60f34332 du 2026-07-28 : 27 minutes de silence, débloquées à la main).

    Ce drapeau est ce que lisent désormais `wake.launch_failed` (enfant TERMINÉ EN ÉCHEC → le
    parent est réveillé et reçoit le motif), `_status.derive_status` (« lancement échoué »,
    testé AVANT `done`) et `closure_guard.child_launched` (le manager ne peut pas se clore
    « terminé » par-dessus). Il est retiré par `tickets.set_launching` (une nouvelle tentative
    est en vol) et par `tickets.add_run` (un agent a démarré)."""
    info = {"error": str(error)[:500], "at": tickets._now()}

    def _apply(fresh: dict) -> None:
        fresh.pop("launching", None)
        # La phase de préparation meurt AVEC le lancement : la laisser afficherait « création
        # du worktree » sur un ticket dont on vient d'acter que rien ne viendra.
        launch_phase.clear_phase(fresh)
        fresh[LAUNCH_FAILED_KEY] = info

    tickets._mutate(slug, ticket["id"], _apply)
    ticket.pop("launching", None)  # miroir sur l'objet appelant
    launch_phase.clear_phase(ticket)
    ticket[LAUNCH_FAILED_KEY] = info
    tickets.add_comment(slug, ticket, f"⚠️ Lancement échoué : {error}", True)


def _launch_bg(*args: Any) -> None:
    """Wrapper tâche de fond : une exception (env provider manquant, git KO) est LOGGÉE,
    jamais avalée en silence, et ne tue pas le process serveur."""
    try:
        _launch(*args)
    except Exception as exc:  # noqa: BLE001 — thread daemon : logguer, ne pas planter le serveur
        slug = args[0] if args and isinstance(args[0], str) else ""
        ticket = args[1] if len(args) > 1 and isinstance(args[1], dict) else {}
        tid = ticket.get("id", "?")
        logging.getLogger(__name__).exception("dispatch._launch_bg a échoué (ticket %s)", tid)
        # Échec de lancement en fond : rendre l'erreur VISIBLE sur le ticket (jamais avalée),
        # retirer l'état 'launching' transitoire, et poser l'issue TERMINALE EN ÉCHEC qui
        # réveille le manager parent au lieu de le laisser attendre un enfant inexistant.
        if slug and ticket.get("id"):
            record_launch_failure(slug, ticket, str(exc))
