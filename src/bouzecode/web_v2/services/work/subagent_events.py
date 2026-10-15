"""Construit les pseudo-messages `subagent_event` intercalés dans le fil d'une
conversation codeur, pour tracer inline le lancement / la complétion des sous-agents
(validate, merge). Plus aucun de ces runs n'est créé (validateur retiré du backend, plus de
résolveur de conflit lancé d'office) : seul l'HISTORIQUE des anciens tickets en porte, et il
reste lisible. Émis côté backend (synthèse à la lecture dans /blocks). Aucune écriture."""
from __future__ import annotations

from bouzecode.web_v2.services.horodatage import cle_chrono, lire_instant

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
    children.sort(key=lambda r: cle_chrono(r.get("started_at")))
    return children


def _group(children: list[dict]) -> list[list[dict]]:
    """Regroupe les lancements du même tour (started_at proches de < _GROUP_WINDOW_SECONDS)."""
    groups: list[list[dict]] = []
    for run in children:
        if groups:
            prev = lire_instant(groups[-1][-1].get("started_at"))
            cur = lire_instant(run.get("started_at"))
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
        "completed": bool(run.get("completed")),
    }


def _ticket_du_codeur(agent) -> dict | None:
    """Le ticket dont `agent` est le CODEUR (run 'work'). Le validateur/merge partagent le
    même ticket : sans cette garde, leur propre conversation afficherait « Validateur lancé »
    (l'illusion que le validateur lance un validateur)."""
    slug = getattr(agent, "ticket_slug", "") or ""
    ticket_id = getattr(agent, "ticket_id", "") or ""
    ticket = tickets.get_ticket(slug, ticket_id) if slug and ticket_id else None
    if not ticket:
        return None
    work_ids = {r.get("agent_id") for r in ticket.get("runs") or []
                if isinstance(r, dict) and r.get("kind") == "work"}
    return ticket if getattr(agent, "agent_id", "") in work_ids else None


def _evenements_du_groupe(group: list[dict]) -> list[dict]:
    agents = [_agent_view(r) for r in group]
    events = [{"role": "subagent_event", "subtype": "launch", "count": len(agents),
               "agents": agents}]
    events += [{"role": "subagent_event", "subtype": "done", "count": 1, "agents": [a]}
               for a in agents if a["completed"]]
    return events


def build_events(agent) -> list[dict]:
    """Retourne les pseudo-messages subagent_event pour la conversation du codeur `agent`.
    Chaque groupe de lancement → un message `launch` ; chaque sous-agent terminé
    (completed) → un message `done`. Liste vide si pas de ticket/sous-agent."""
    ticket = _ticket_du_codeur(agent)
    if ticket is None:
        return []
    return [event for group in _group(_child_runs(ticket))
            for event in _evenements_du_groupe(group)]


