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
injectable), `report` RECENSE (elle lit le store) ; le recensement vit dans `activity_parc`,
`report` reste ici comme point d'entrée : la seconde n'est que la première appliquée au parc.
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


# Outils dont l'appel INTERROMPT le tour en attendant l'utilisateur : jamais un repli
# d'activité valable (cf. `current_tools`).
_OUTILS_SUSPENSIFS = {"AskUserQuestion"}


def current_tools(status: dict, meta: dict) -> tuple[list[str], bool]:
    """(outils, en_direct). `en_direct` distingue « le process dit qu'il exécute ceci
    MAINTENANT » de « voici le dernier outil qu'on a vu passer », deux affirmations de
    fiabilité très différentes qu'il ne faut jamais présenter du même ton."""
    live = [t for t in (status.get("tools") or []) if t]
    if live:
        return live, True
    recorded = meta.get("last_tool") or ""
    # Un outil qui SUSPEND le tour ne peut pas être le dernier outil « vu » d'un agent
    # qu'on regarde tourner : s'il tourne, c'est que la question a été répondue et que la
    # suite du lot s'exécute. Le resservir figeait l'activité sur « AskUserQuestion » tour
    # après tour (2026-09-29) et faisait croire l'agent en boucle sur sa question.
    if recorded in _OUTILS_SUSPENSIFS:
        return [], False
    return ([recorded], False) if recorded else ([], False)


def children_index(pairs) -> dict[str, list[str]]:
    """parent -> identifiants de ses enfants VIVANTS, depuis des couples (parent, enfant).

    Pur et donc testable sans runner ni store : c'est la SEULE information qui permette de
    dire d'un parent silencieux qu'il attend légitimement. Elle n'existe que du côté des
    enfants (`agent.parent`), jamais du côté du parent bloqué dans `_wait_for_child`.
    """
    index: dict[str, list[str]] = {}
    for parent, child in pairs:
        if not parent or not child:
            continue
        index.setdefault(parent, []).append(child)
    return index


def _suffixe(age: str, gabarit: str) -> str:
    return gabarit.format(age=age) if age else ""


def _activite(state: str, tools: list[str], live: bool, attend_enfant: bool,
              waiting_for: list[str] | None, age: str) -> tuple[str, str]:
    """(activité, phrase). Une attente ou un démarrage se DÉCRIT par son état, pas par un
    outil : nommer le dernier outil d'un agent qui attend une réponse ferait croire qu'il
    travaille. « En cours » (le process le dit) et « dernier vu » ne se disent pas du même ton."""
    if attend_enfant:
        return ("waiting_for_child",
                f"attend son enfant ({', '.join(waiting_for)})" + _suffixe(age, " depuis {age}"))
    if state in _LABELS_BY_STATE:
        return state, _LABELS_BY_STATE[state]
    if tools:
        activite = "+".join(tools)
        if live:
            return activite, f"{activite} en cours" + _suffixe(age, " depuis {age}")
        return activite, f"dernier outil vu : {activite}" + _suffixe(age, ", il y a {age}")
    return "llm", "appel au modèle" + _suffixe(age, " depuis {age}")


def describe(status: dict, meta: dict, now: float | None = None,
             waiting_for: list[str] | None = None) -> dict:
    """Activité d'un agent : {} s'il n'est pas vivant, sinon
    {activity, activity_label, last_event_at, idle_seconds, stale, turn}.

    `activity_label` est la PHRASE unique que rendent l'interface et l'API : deux surfaces ne
    peuvent plus décrire la même seconde avec deux vocabulaires. Pur : `now` injectable,
    aucune I/O — les preuves sont lues en amont par `store.agent_status` et l'index de sessions."""
    state = status.get("state") or ""
    if state not in _LIVE_STATES:
        return {}
    now = time.time() if now is None else now
    last_event_at = float(status.get("last_event_at") or 0.0)
    idle_seconds = int(now - last_event_at) if last_event_at else -1
    tools, live = current_tools(status, meta)
    # ATTENTE SYNCHRONE ET NORMALE d'un parent : `Agent` tenu EN DIRECT alors qu'un enfant
    # vivant le déclare comme parent (`multi_agent.attente_web._wait_for_child`). Sans battement,
    # elle ressemblait à un agent planté. Un `Agent` seulement ENREGISTRÉ ne prouve rien.
    attend_enfant = bool(waiting_for) and live and "Agent" in tools
    activity, label = _activite(state, tools, live, attend_enfant, waiting_for,
                                human_age(idle_seconds))
    view = {
        "activity": activity,
        "activity_label": label,
        "last_event_at": last_event_at,
        "idle_seconds": idle_seconds,
        # Aucun battement depuis trop longtemps : à REGARDER, jamais un verdict de mort — sauf
        # pendant une attente d'enfant, où le silence est attendu.
        "stale": bool(state == "running" and idle_seconds >= STALE_AFTER_SECONDS
                      and not attend_enfant),
    }
    if attend_enfant:
        view["waiting_for"] = list(waiting_for)  # les tickets attendus, vérifiables
    if int(status.get("ipc_turn") or 0):
        view["turn"] = int(status["ipc_turn"])
    return view


def report() -> dict:
    """Recensement des agents VIVANTS et des tickets en lancement (`activity_parc.report`)."""
    from .activity_parc import report as recenser
    return recenser()
