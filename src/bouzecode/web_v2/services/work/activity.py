# [desc] Ce que fait un agent VIVANT, en une phrase : outil en cours, tour, et âge du dernier battement. [/desc]
"""Traduit le statut brut d'un agent en ACTIVITÉ lisible, pour l'UI comme pour un agent de
monitoring.

LE TROU QU'ON BOUCHE. `state` ne dispose que de cinq mots (running / idle / awaiting_input /
starting / finished) et aucun ne dit ce que l'agent FAIT. Mesuré sur l'agent eac1f0bef295 :
« en cours » pendant onze minutes, sans rien pour distinguer un travail en profondeur (il
pilotait un chrome-devtools-mcp) d'un blocage. Les preuves existaient toutes sur le disque —
l'horodatage de chaque changement d'état IPC, le tour courant, le dernier outil enregistré
dans la session — et personne ne les servait.

DEUX SOURCES, dans cet ordre :
  1. l'IPC (`status.tools`), publié par `dag._announce_activity` au démarrage de chaque lot
     d'outils : c'est le seul signal VIVANT pendant l'exécution d'un outil ;
  2. le dernier outil enregistré dans la session (`meta["last_tool"]`), pour les agents lancés
     par une version antérieure du harnais, qui ne publient rien.
Aucune troisième règle : quand les deux se taisent, on dit « appel au modèle » si l'agent
tourne — c'est la seule autre chose qu'un agent en cours puisse être en train de faire.

Deux fonctions, deux natures : `describe` est PURE (elle traduit des preuves déjà lues, `now`
injectable), `report` RECENSE (elle lit le store). Elles vivent ensemble parce qu'elles
répondent à la même question, et que la seconde n'est que la première appliquée au parc.
"""
from __future__ import annotations

import time

# Vivacités pour lesquelles une activité a du SENS. Sur un agent terminé, « Bash il y a 3 j »
# n'informe personne et alourdirait chacun des ~250 nodes de l'arbre : champ absent = rien à
# dire (même convention que `allow_freetext` dans `fleet._node`).
_LIVE_STATES = frozenset({"running", "starting", "idle",
                          "awaiting_input", "awaiting_plan_validation"})

# Au-delà, un agent « en cours » qui n'a pas battu mérite d'être SIGNALÉ. 4 minutes : au-dessus
# de la quasi-totalité des outils (un `pytest -n auto` du projet, un `git worktree add` de 50 s,
# un appel LLM long) et bien en dessous du quart d'heure qu'on a laissé passer sans rien voir.
# Ce seuil ne conclut RIEN — il ne déclenche aucune action, il attire l'œil.
STALE_AFTER_SECONDS = 240

_LABELS_BY_STATE = {
    "starting": "démarrage du process",
    "idle": "chaud et oisif, joignable",
    "awaiting_input": "attend une réponse de l'utilisateur",
    "awaiting_plan_validation": "attend la validation du plan",
}


def human_age(seconds: float) -> str:
    """Durée en français court : « 12 s », « 4 min », « 1 h 07 ». Vide si inconnue (<0)."""
    if seconds < 0:
        return ""
    if seconds < 60:
        return f"{int(seconds)} s"
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    return f"{int(seconds // 3600)} h {int((seconds % 3600) // 60):02d}"


def current_tools(status: dict, meta: dict) -> tuple[list[str], bool]:
    """(outils, en_direct). `en_direct` distingue « le process dit qu'il exécute ceci
    MAINTENANT » de « voici le dernier outil qu'on a vu passer », deux affirmations de
    fiabilité très différentes qu'il ne faut jamais présenter du même ton."""
    live = [t for t in (status.get("tools") or []) if t]
    if live:
        return live, True
    recorded = meta.get("last_tool") or ""
    return ([recorded], False) if recorded else ([], False)


def describe(status: dict, meta: dict, now: float | None = None) -> dict:
    """Activité d'un agent : {} s'il n'est pas vivant, sinon
    {activity, activity_label, last_event_at, idle_seconds, stale, turn}.

    `activity_label` est la PHRASE unique que rendent l'interface et l'API : deux surfaces ne
    peuvent plus décrire la même seconde avec deux vocabulaires (c'est déjà arrivé, cf.
    `liveness.classify_ticket`). Pur : `now` injectable, aucune I/O — les preuves sont lues en
    amont par `store.agent_status` et l'index de sessions."""
    state = status.get("state") or ""
    if state not in _LIVE_STATES:
        return {}
    now = time.time() if now is None else now
    last_event_at = float(status.get("last_event_at") or 0.0)
    idle_seconds = int(now - last_event_at) if last_event_at else -1
    age = human_age(idle_seconds)

    tools, live = current_tools(status, meta)
    if state in _LABELS_BY_STATE:
        # Une attente ou un démarrage se DÉCRIT par son état, pas par un outil : nommer le
        # dernier outil d'un agent qui attend une réponse ferait croire qu'il travaille.
        activity, label = state, _LABELS_BY_STATE[state]
    elif tools and live:
        activity = "+".join(tools)
        label = f"{activity} en cours" + (f" depuis {age}" if age else "")
    elif tools:
        activity = "+".join(tools)
        label = f"dernier outil vu : {activity}" + (f", il y a {age}" if age else "")
    else:
        activity = "llm"
        label = "appel au modèle" + (f" depuis {age}" if age else "")

    view = {
        "activity": activity,
        "activity_label": label,
        "last_event_at": last_event_at,
        "idle_seconds": idle_seconds,
        # Aucun battement depuis trop longtemps : à REGARDER, jamais un verdict de mort.
        # L'agent peut très bien tenir un outil légitimement long — c'est le silence qu'on
        # signale, pas l'agent.
        "stale": bool(state == "running" and idle_seconds >= STALE_AFTER_SECONDS),
    }
    turn = int(status.get("ipc_turn") or 0)
    if turn:
        view["turn"] = turn
    return view


def report() -> dict:
    """Recensement des agents VIVANTS et des tickets en cours de lancement, avec ce qu'ils font.

    Réponse à un besoin qui n'était servi par AUCUN endpoint : savoir ce que fait la flotte.
    Les agents de monitoring appelaient donc `/api/agents/tree`, dont la variante complète
    coûte 9,45 s (929 Ko) parce qu'elle paie les infos git de ~250 nodes, les prompts entiers
    et les agents terminés — pour n'en lire qu'une poignée de champs. Ici : aucun subprocess
    git, aucun prompt, aucun agent terminé.

    Trié : les agents qui attendent une réponse d'abord (c'est là qu'il faut agir), puis les
    silencieux anormaux, puis les autres."""
    from ..sessions import store
    from ...runtime import runner
    from . import launch_phase, projects, tickets

    rows = []
    meta_cache: dict = {}
    for agent in runner.list_agents():
        # ORDRE VOULU : le statut d'abord (IPC + pid, quelques octets), et la méta de session
        # SEULEMENT pour les agents qui se révèlent vivants. Passer par le listing du parc
        # (`list_agent_sessions`) coûtait le décodage de toutes les sessions dont le mtime avait
        # bougé — 13,7 s mesurées à froid — pour n'utiliser au bout du compte que le dernier
        # outil de trois agents.
        status = store.agent_status(agent)
        if describe(status, {}) == {}:
            continue  # agent terminé : rien à dire, et c'est le gros du parc
        view = describe(status, store.agent_meta(agent, meta_cache))
        rows.append({
            "agent_id": agent.agent_id,
            "key": f"agent/{agent.agent_id}",
            "state": status.get("state", ""),
            # Phase de DÉMARRAGE (cf. store.demarrage_phase). Elle était calculée ici à chaque
            # passage puis jetée, alors que c'est la seule chose à dire d'un agent pendant les
            # secondes où « en cours » est vrai mais muet. Servie ici, elle donne à ce
            # recensement — le seul assez bon marché pour être appelé souvent — de quoi
            # rafraîchir la sidebar sans recalculer l'arbre (cf. `fleet_live`).
            "phase": status.get("phase", ""),
            "ticket_id": getattr(agent, "ticket_id", "") or "",
            "parent": agent.parent or "",
            "title": (agent.prompt or "").strip().split("\n")[0][:80],
            "question": status.get("question", ""),
            **view,
        })
    project_names = {p["slug"]: p["name"] for p in projects.list_projects()}
    for slug, ticket in tickets.launching_tickets():
        rows.append({
            "agent_id": "", "key": f"launching/{ticket['id']}",
            "state": "provisioning", "ticket_id": ticket["id"],
            "parent": ticket.get("parent") or "",
            "title": ticket.get("title") or "Nouvelle conversation",
            "project_name": project_names.get(slug, ""),
            # Un lancement n'a pas d'activité d'agent : sa phase EST son activité.
            "activity_label": launch_phase.phase_view(ticket).get(
                "phase_label", "préparation en cours"),
            **launch_phase.phase_view(ticket),
        })
    rows.sort(key=lambda r: (0 if r["state"].startswith("awaiting") else
                             1 if r.get("stale") else 2, r["title"]))
    return {"agents": rows, "count": len(rows),
            "awaiting": sum(1 for r in rows if r["state"].startswith("awaiting")),
            "stale": sum(1 for r in rows if r.get("stale"))}
