"""Construit les pseudo-messages `subagent_event` intercalés dans le fil d'une
conversation codeur, pour tracer inline le lancement / la complétion des sous-agents
(validate, merge). Émis côté backend (synthèse à la lecture dans /blocks) → correct
après reload ET sur sessions historiques (backfill). Aucune écriture dans la session."""
from __future__ import annotations

from datetime import datetime

from bouzecode.web_v2.services.work import tickets

# Un run compte comme SOUS-AGENT distinct (marqueur) SSI son kind est validate/merge ET
# son agent_id n'est PAS celui d'un run 'work' (les runs work + un merge sur le codeur =
# reprises du MÊME agent via continue_agent, PAS un lancement de sous-agent).
_CHILD_KINDS = ("validate", "merge")
_ROLE_BY_KIND = {"validate": "Validateur", "merge": "Merge", "work": "Agent"}
# Deux lancements espacés de moins de ce seuil = même tour → groupés en un seul bloc.
_GROUP_WINDOW_SECONDS = 90


def _role(kind: str) -> str:
    return _ROLE_BY_KIND.get(kind, kind.capitalize() if kind else "Agent")


def _parse(started_at: str) -> datetime | None:
    if not started_at:
        return None
    try:
        return datetime.fromisoformat(started_at.rstrip("Z"))
    except ValueError:
        return None


def _label(kind: str) -> str:
    # L'heure n'est PLUS cuite ici : le front la dérive de `started_at` (ISO UTC)
    # via un helper unique (heure locale). Le label reste le rôle seul.
    return _role(kind)


def _child_runs(ticket: dict) -> list[dict]:
    """Runs = vrais sous-agents lancés (kind validate/merge, agent_id distinct des runs work),
    triés par started_at croissant (ordre chronologique du fil)."""
    runs = [r for r in ticket.get("runs") or [] if isinstance(r, dict)]
    work_ids = {r.get("agent_id") for r in runs if r.get("kind") == "work"}
    children = [
        r for r in runs
        if r.get("kind") in _CHILD_KINDS and r.get("agent_id") not in work_ids
    ]
    children.sort(key=lambda r: r.get("started_at") or "")
    return children


def _group(children: list[dict]) -> list[list[dict]]:
    """Regroupe les lancements du même tour (started_at proches de < _GROUP_WINDOW_SECONDS)."""
    groups: list[list[dict]] = []
    for run in children:
        if groups:
            prev = _parse(groups[-1][-1].get("started_at") or "")
            cur = _parse(run.get("started_at") or "")
            if prev is not None and cur is not None and abs((cur - prev).total_seconds()) < _GROUP_WINDOW_SECONDS:
                groups[-1].append(run)
                continue
        groups.append([run])
    return groups


def _agent_view(run: dict) -> dict:
    agent_id = run.get("agent_id") or ""
    kind = run.get("kind") or ""
    started = run.get("started_at") or ""
    return {
        "agent_id": agent_id,
        "kind": kind,
        "role": _role(kind),
        "label": _label(kind),
        "started_at": started,  # ISO UTC brut — le front formate l'heure (local)
        "open_key": f"agent/{agent_id}",
        "verdict": run.get("verdict") or "",
        "completed": bool(run.get("completed")),
    }


def build_events(agent) -> list[dict]:
    """Retourne les pseudo-messages subagent_event pour la conversation du codeur `agent`.
    Chaque groupe de lancement → un message `launch` ; chaque sous-agent terminé
    (completed OU verdict) → un message `done`. Liste vide si pas de ticket/sous-agent."""
    slug = getattr(agent, "ticket_slug", "") or ""
    ticket_id = getattr(agent, "ticket_id", "") or ""
    if not slug or not ticket_id:
        return []
    ticket = tickets.get_ticket(slug, ticket_id)
    if not ticket:
        return []
    # Les events launch/done ne s'affichent QUE dans la conversation du CODEUR (run 'work').
    # Le validateur/merge PARTAGENT le même ticket que le codeur : sans ce garde, ouvrir la
    # conv d'un sous-agent (validate/merge) rejouerait _child_runs sur le même ticket et
    # afficherait "Validateur lancé / terminé" DANS sa propre conversation — l'illusion
    # "le validateur lance un validateur". On identifie le codeur par agent_id ∈ work_ids.
    runs = [r for r in ticket.get("runs") or [] if isinstance(r, dict)]
    work_ids = {r.get("agent_id") for r in runs if r.get("kind") == "work"}
    if getattr(agent, "agent_id", "") not in work_ids:
        return []
    children = _child_runs(ticket)
    if not children:
        return []
    events: list[dict] = []
    for group in _group(children):
        agents = [_agent_view(r) for r in group]
        events.append({
            "role": "subagent_event",
            "subtype": "launch",
            "count": len(agents),
            "agents": agents,
        })
        done = [a for a in agents if a["completed"] or a["verdict"]]
        for a in done:
            events.append({
                "role": "subagent_event",
                "subtype": "done",
                "count": 1,
                "agents": [a],
            })
    return events
