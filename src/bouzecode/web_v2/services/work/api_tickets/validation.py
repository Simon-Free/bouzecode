# [desc] Validation STRICTE d'une création / d'un lancement de ticket : titre, prompt, isolation (énumération, jamais de bascule silencieuse), profil, modèle, branches, parent. Rien n'est créé avant. [/desc]
"""Tout ce que `POST /api/projects/{slug}/tickets` vérifie AVANT de créer quoi que ce soit (spec
§5.1, §6.2). Un échec lève `Refus` (400) : aucun ticket fantôme.

Isolation (constat C8, décision D3) : la valeur est l'une de `shared`, `worktree`,
`worktree_venv` (`worktree+venv` accepté, forme historique) ; toute autre valeur est refusée
(400 `isolation_inconnue`) — plus jamais de repli silencieux en `shared`. Un appel MANAGER (un
agent parent) doit la donner (400 `isolation_requise`) ; l'UI humaine reçoit `worktree` par
défaut, ou `shared` si le projet n'est pas un dépôt git (aucun worktree possible)."""
from __future__ import annotations

from ..isolation import SHARED, WORKTREE, WORKTREE_VENV
from .refus import Refus

TITRE_MAX, PROMPT_MAX = 200, 200_000
ISOLATIONS = {"shared": SHARED, "worktree": WORKTREE, "worktree_venv": WORKTREE_VENV,
              "worktree+venv": WORKTREE_VENV}


def titre_et_prompt(payload: dict) -> tuple[str, str]:
    titre = str(payload.get("title") or "").strip()
    prompt = str(payload.get("prompt") or "").strip()
    manquants = [nom for nom, valeur in (("title", titre), ("prompt", prompt)) if not valeur]
    if manquants:
        raise Refus("champ_requis", f"champ(s) requis : {', '.join(manquants)}", 400,
                    champs=manquants)
    if len(titre) > TITRE_MAX:
        raise Refus("titre_trop_long", f"le titre dépasse {TITRE_MAX} caractères", 400,
                    longueur=len(titre), max=TITRE_MAX)
    if len(prompt) > PROMPT_MAX:
        raise Refus("prompt_trop_long", f"le prompt dépasse {PROMPT_MAX} caractères", 400,
                    longueur=len(prompt), max=PROMPT_MAX)
    return titre, prompt


def parent(payload: dict) -> tuple[str, str]:
    """(agent_id, ticket_id) du manager qui crée le ticket ; ('', '') pour un humain.
    Accepte `{agent_id, ticket_id}` (spec §3.1) ou un agent_id seul (forme historique)."""
    from ..dispatch import is_managed_parent
    brut = payload.get("parent")
    if isinstance(brut, dict):
        agent_id, ticket_id = str(brut.get("agent_id") or ""), str(brut.get("ticket_id") or "")
    else:
        agent_id, ticket_id = str(brut or ""), ""
    agent_id = agent_id.strip().removeprefix("agent/")
    return (agent_id, ticket_id.strip()) if is_managed_parent(agent_id) else ("", "")


def isolation(valeur, manager: bool, depot_git: bool) -> str:
    """L'isolation demandée, normalisée ; jamais devinée pour un manager."""
    brute = str(valeur or "").strip().lower()
    if not brute:
        if manager:
            raise Refus("isolation_requise", "un agent qui crée un ticket doit choisir son "
                        "isolation : shared, worktree ou worktree_venv", 400,
                        attendues=sorted(ISOLATIONS))
        return WORKTREE if depot_git else SHARED
    if brute not in ISOLATIONS:
        raise Refus("isolation_inconnue", f"isolation inconnue : {brute!r} (attendu : shared, "
                    "worktree ou worktree_venv)", 400, recue=brute, attendues=sorted(ISOLATIONS))
    mode = ISOLATIONS[brute]
    if mode != SHARED and not depot_git:
        raise Refus("isolation_impossible", f"isolation {brute!r} impossible : le projet "
                    "n'est pas un dépôt git (seul `shared` est possible)", 400, recue=brute)
    return mode


def profil(nom: str, project_path: str) -> str:
    """Un profil NOMMÉ doit exister au catalogue (typologies du projet + agents système)."""
    from ...typologies import get_typology
    nom = str(nom or "").strip()
    if nom in ("", "default"):
        return ""
    if get_typology(nom, project_path) is None:
        raise Refus("profil_inconnu", f"profil inconnu : {nom!r}", 400, profil=nom)
    return nom


def modele(nom: str) -> str:
    from .....backend.agent.providers.registry import PROVIDERS
    nom = str(nom or "").strip()
    connus = {m for fournisseur in PROVIDERS.values() for m in fournisseur.get("models", [])}
    if nom and nom not in connus:
        raise Refus("modele_inconnu", f"modèle inconnu : {nom!r} (voir GET /api/models)", 400,
                    modele=nom)
    return nom


def branches(project: dict, mode: str, payload: dict) -> tuple[str, str]:
    """(resume_branch, work_branch). Une branche de travail doit exister et être libre ; ni
    l'une ni l'autre n'a de sens en `shared` (400 `isolation_incompatible`)."""
    from .. import existing_branch, repos
    reprise = str(payload.get("resume_branch") or "").strip()
    travail = str(payload.get("work_branch") or "").strip()
    if (reprise or travail or payload.get("ephemeral")) and mode == SHARED:
        raise Refus("isolation_incompatible", "une branche de travail, une branche de départ ou "
                    "un ticket éphémère exigent un worktree : isolation `shared` impossible", 400)
    if travail:
        racine = repos.repo_root(project["path"])
        motif = existing_branch.unavailable_reason(racine, travail) if racine else "pas un dépôt git"
        if motif:
            raise Refus("branche_introuvable", motif, 400, work_branch=travail)
    return reprise, travail
