# [desc] Les nœuds de l'arbre des agents : nœud d'agent (relevé commun `parc.releve` + ce que l'arbre ajoute), nœuds synthétiques des tickets en lancement (`launching/<ticket>`) et des lancements échoués récents (`failed/<ticket>`). [/desc]
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ...runtime.runner import agent_chaud
from ..sessions import category, store
from . import activity, launch_phase, liveness, parc, repos, tickets, worktrees
from .etat_ticket import vue_rattachee
from .fsm import etats

# run_kind → rôle lisible. Repli = run_kind.capitalize() pour tout kind inconnu.
_ROLE_BY_RUN_KIND = {"work": "Agent"}


def _short_label(agent) -> str:
    """Libellé court d'un nœud : ce qu'on DEMANDE à l'agent (`titres.titre_lisible` : l'objectif
    du brief, pas une 1re ligne de contexte ni un gabarit) pour une conversation de travail ; le
    titre de l'agent repris pour une reprise ; le rôle lisible pour un agent structurel."""
    from bouzecode.web_v2.runtime.runner.agent_reprise import RESUME_PROMPT
    from .titres import titre_lisible
    if (agent.run_kind or "work") != "work":
        return _ROLE_BY_RUN_KIND.get(agent.run_kind) or (agent.run_kind or "Agent").capitalize()
    if getattr(agent, "titre", ""):
        return agent.titre[:60]
    if (agent.prompt or "").strip() == RESUME_PROMPT:
        return "Reprise d'un agent arrêté"
    #  60 caractères : ce qui tient dans la barre latérale (`title_full` garde tout).
    return titre_lisible(agent.prompt or "")[:60] or "Agent"


def _repo_fields(agent, avec_git: bool = True) -> dict:
    """`avec_git=False` : aucun subprocess git (l'appelant ne lit pas repo/branch).

    Mesuré : résoudre repo/branche coûtait 5,6 s sur l'arbre complet, payés pour rien par
    l'inbox du Bureau, dont la carte « agent arrêté » n'affiche ni dépôt ni branche."""
    if not agent.cwd or not avec_git:
        return {"repo": "", "branch": ""}
    key = repos.repo_key(agent.cwd)
    return {"repo": repos.repo_name(agent.cwd, key), "branch": repos.branch_of(agent.cwd)}


def _suspect_dead(agent, state: str, turns: int) -> bool:
    """Fini SANS aucun tour ET rc non nul/absent. rc=0 est un succès propre, jamais suspect."""
    return state == "finished" and turns == 0 and agent.returncode != 0


def _node(agent, meta: dict, project_list: list[dict], avec_git: bool = True) -> dict[str, Any]:
    status = meta.get("status") or store.agent_status(agent)
    turns = meta.get("turn_count", 0)
    # Vivacité DÉRIVÉE DE PREUVES (pid vivant + close_reason + final_answer), mêmes helpers
    # que GET /api/agents?state=interrupted et la liste des tickets.
    vivacite = liveness.classify_agent(agent)
    commun = parc.releve(agent, project_list, status)
    return {
        **commun,
        #  Process vivant et idle : reprise chaude possible. Un returncode n'est stampé que sur un
        #  process constaté absent : inutile d'interroger l'OS pour les ~500 agents finis.
        "warm": agent.returncode is None and agent_chaud.is_warm(agent),
        "last_activity": max(agent.started_at or "", agent.finished_at or "", meta.get("saved_at", "")),
        "session_path": agent.session_path or "",
        "title": _short_label(agent),
        "title_full": (agent.prompt or "").strip(),
        **_repo_fields(agent, avec_git),
        "isolated": str(worktrees.WORKTREES_DIR) in (agent.cwd or ""),
        "model": agent.model,
        "returncode": agent.returncode,
        "saved_at": meta.get("saved_at", ""),  # dernière interaction : clé de tri
        "turn_count": turns,
        "has_recap": bool(meta.get("has_recap")),
        "suspect_dead": _suspect_dead(agent, commun["state"], turns),
        "kind": agent.run_kind or "",  # work/merge…
        "category": category.classify_agent(agent),  # même classifieur que /api/sessions
        "liveness": vivacite,
        # Livré parce que son ticket est INTÉGRÉ (même s'il a été tué juste après) : libellé dédié.
        "integre": vivacite == "delivered" and liveness.travail_integre(agent),
        "interrupted": vivacite == "crashed",
        # Fin CONSTATÉE par le serveur (process disparu, pid réutilisé…) : la raison lisible.
        "raison_arret": getattr(agent, "fin_constatee", "") or "",
        **activity.describe(status, meta),  # ce que l'agent fait (agents vivants seulement)
    }


def _synthetic_node(ticket: dict, slug: str, project: dict, **fields) -> dict:
    """Nœud d'un ticket sans agent (en lancement ou lancement échoué)."""
    ident = ticket["id"]
    base = {"agent_id": ident, "ticket_id": ident, "session_path": "",
            "parent": ticket.get("parent") or "", "title_full": (ticket.get("prompt") or "").strip(),
            "project_slug": slug, "project_name": project["name"], "repo": "", "branch": "",
            "model": ticket.get("model") or "", "phase": "", "question": "", "options": [],
            "returncode": None, "started_at": ticket.get("created_at") or "", "saved_at": "",
            "turn_count": 0, "has_recap": False, "suspect_dead": False, "kind": "work"}
    return {**base, **fields}


def _launching_node(ticket: dict, slug: str, project: dict) -> dict:
    # La catégorie est déduite comme pour un agent (prompt + parent) : la conversation ne
    # doit pas changer de catégorie au spawn.
    categorie = category.classify_agent(SimpleNamespace(
        agent_id=ticket["id"], prompt=ticket.get("prompt") or ticket.get("title") or "",
        parent=ticket.get("parent") or ""))
    return _synthetic_node(
        ticket, slug, project,
        key=f"launching/{ticket['id']}", title=ticket.get("title") or "Nouvelle conversation",
        isolated=True, state="provisioning", category=categorie, liveness="running",
        **launch_phase.phase_view(ticket))  # phase courante : worktree, uv sync, spawn…


def _launching_nodes(project_list: list[dict], have_ticket: set) -> list[dict]:
    """Tickets en cours de lancement dont aucun agent n'existe encore. Un slug hors du
    registre des projets serait inouvrable : ignoré ; le vrai nœud agent prime toujours."""
    project_by_slug = {p["slug"]: p for p in project_list}
    return [_launching_node(ticket, slug, project_by_slug[slug])
            for slug, ticket in tickets.launching_tickets()
            if slug in project_by_slug and ticket["id"] not in have_ticket]


def _failed_at(ticket: dict) -> str:
    return str((ticket.get("state_reason") or {}).get("at") or ticket.get("created_at") or "")


def _failed_launch_to_show(slug: str, ticket: dict, deja: set, project_by_slug: dict) -> bool:
    from . import inbox
    ident = str(ticket.get("id") or "")
    if ticket.get("state") != etats.LAUNCH_FAILED or not ident or ident in deja:
        return False
    if slug not in project_by_slug or ticket.get("archived") or ticket.get("runs"):
        return False
    return inbox._recent(_failed_at(ticket))


def _noeuds_lancement_echoue(tous: list, par_ticket: dict, deja: set,
                             project_by_slug: dict) -> list[dict]:
    """Tickets dont le lancement a échoué (< 7 jours, ni done ni archivés) : sans ce nœud, la
    carte provisoire du front restait « démarrage » pour toujours."""
    from . import lexique
    noeuds = []
    for slug, ticket in tous:
        if not _failed_launch_to_show(slug, ticket, deja, project_by_slug):
            continue
        lien = par_ticket.get(str(ticket["id"])) or {}
        noeuds.append(_synthetic_node(
            ticket, slug, project_by_slug[slug],
            key=f"failed/{ticket['id']}", title=ticket.get("title") or "Conversation",
            isolated=False, state="launch_failed", saved_at=_failed_at(ticket),
            category="user", liveness="crashed", interrupted=False,
            launch_error=str((ticket.get("state_reason") or {}).get("message") or ""),
            etat="launch_failed", libelle_etat=lexique.libelle_etat("launch_failed"),
            micro_id=lien.get("micro_id", ""), tache_titre=lien.get("titre", ""),
            **vue_rattachee(ticket)))
    return noeuds
