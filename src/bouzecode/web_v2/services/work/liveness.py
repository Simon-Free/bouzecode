"""Vivacité d'un AGENT, dérivée de preuves (process, IPC, session) — détection seulement.

Ce module ne décide plus de l'état d'un TICKET : `ticket.state` est persisté et écrit par
`ticket_fsm` (spec B2). Il répond à « que fait cet agent ? » pour les vues d'agents (arbre,
conversations, Bureau) et fournit au watchdog (`constats`) ce qu'il constate :
'running' | 'idle' | 'awaiting_input' | 'missing' | 'delivered' | 'crashed'.
Un agent mort est `delivered` si sa clôture prouve une livraison selon la SEULE table
`close_reasons.issue_de_fin` (C14 : une fin forcée n'est jamais une livraison), `crashed` sinon.
"""
from __future__ import annotations

from pathlib import Path

from ... import close_reasons
from ...runtime.runner import agent_fiche, agent_vivacite
from ..sessions import empreintes, store
from .distant import runs as runs_distants

# close_reasons de CRASH franc (mort infra / interruption non-gracieuse). `cancelled`
# est inclus : un arrêt utilisateur laisse un ticket à RELANCER à la main, exactement
# comme un crash du point de vue de la classification (aucune livraison prouvée).
CRASH_CLOSE_REASONS = close_reasons.CRASH_CLOSE_REASONS

# Clôtures CONTRÔLÉES (non-crash) émises par execute_tool_calls / handle_no_tools :
# les clôtures gracieuses PLUS les fins forcées mais maîtrisées (nudge épuisé, meta-only).
# Toutes signifient « la boucle a décidé de clore », jamais « le process est mort en vol ».
CLEAN_CLOSE_REASONS = close_reasons.CONTROLLED_CLOSE_REASONS


def _session_path(agent_id: str, agent) -> Path:
    """Chemin de la session sur disque, reconstruit depuis AGENTS_DIR si l'agent a été
    déchargé (nettoyé après mort). MÊME logique que wake._reconcile_graceful_close."""
    session_path = getattr(agent, "session_path", "") or ""
    if not session_path:
        session_path = str(agent_fiche.AGENTS_DIR / f"{agent_id}.session.json")
    return Path(session_path)


# Clôture lue sur disque, retenue par VERSION du fichier de session (`empreintes`) : décoder la
# session ENTIÈRE (jusqu'à 100 Mo sous Windows) pour deux champs, à chaque classification d'un
# agent mort, coûtait 10 s par `/api/nav/counts` à froid sur un parc de 480 agents. La mémoire
# de process qui l'évitait se perdait à chaque redémarrage (712 sessions redécodées par le
# premier `/api/inbox`, 63 s cache froid) : elle est désormais persistée, ~100 octets par agent.
_CLOTURES = empreintes.Empreintes("clotures_sessions.json", version=1)


def _cloture_lue(path: Path) -> dict | None:
    data = store.load_session_json(path)
    if data is None:  # en cours d'écriture ou illisible : rien à retenir
        return None
    return {"close_reason": data.get("close_reason") or "",
            "final_answer": bool(data.get("final_answer"))}


def _session_data(agent_id: str, agent) -> dict:
    """`close_reason` et `final_answer` (vérité seulement) de la session, lus UNE fois par
    version du fichier, puis relus de l'empreinte persistée."""
    path = _session_path(agent_id, agent)
    return _CLOTURES.lire(path, lambda: _cloture_lue(path)) or {}


def oublier_clotures() -> None:
    """Oublie la mémoire des clôtures (isolation des tests ; le fichier reste)."""
    _CLOTURES.oublier()


# Vivacités qui prouvent qu'un agent n'est PAS fini. `awaiting_input` en fait partie :
# il est VIVANT au sens du workflow (rien n'est joué, son travail reprend dès qu'on lui
# répond) tout en étant la seule vivacité qui réclame un geste HUMAIN. Le confondre avec
# `running`, comme avant, rendait indétectable « quels agents attendent ma réponse ».
AWAITING = "awaiting_input"

# `idle` : CHAUD MAIS OISIF. Le process est résident dans le warm pool — il a fini son
# tour, il n'en joue aucun, et il reprend in-process au premier message. VIVANT (il tient
# son worktree, il est joignable) mais surtout PAS « en train de travailler » : l'annoncer
# `running`, comme avant, présentait l'inaction comme du travail dans l'arbre de flotte et
# dans les listes, pendant que la garde anti-double-tour le rendait injoignable.
# Même geste que pour AWAITING : une vivacité de PLUS, pas un vocabulaire concurrent —
# le mot `idle` est déjà celui que le process écrit lui-même dans son IPC.
IDLE = "idle"
ALIVE = frozenset({"running", AWAITING, IDLE})

# Un run dont l'ENREGISTREMENT d'agent a disparu de `AGENTS_DIR` : `runner.load_agent`
# renvoie None. Ce n'est PAS un crash — le process a pu très bien tourner, et tourner
# ENCORE : c'est nous qui avons perdu la fiche. Les deux étaient confondus sous `crashed`,
# si bien qu'un agent devenu injoignable (fiche déplacée en corbeille alors qu'il vivait)
# se présentait comme un banal plantage. On le NOMME : c'est une anomalie d'inventaire,
# elle se répare en restaurant la fiche, pas en relançant l'agent.
MISSING = "missing"


def classify_agent_run(ticket: dict, run: dict, agent=None) -> str:
    """Classe UN run : 'running' | 'awaiting_input' | 'idle' | 'missing' | 'delivered'
    | 'crashed'.

    - running       : process vivant (pid) et en train de travailler.
    - idle          : process vivant mais OISIF (warm pool, tour fini). Joignable — un
                      message repart in-process — sans être « en cours ».
    - awaiting_input: bloqué sur une question posée à l'utilisateur (état IPC, ou
                      question pendante sur disque une fois l'IPC écrasé). VIVANT.
    - missing       : l'enregistrement de l'agent est INTROUVABLE — on ne peut plus rien
                      dire de lui, ni le joindre.
    - delivered     : mort ET clôture prouvée propre (close_reason clean, OU final_answer
                      présent) — hors abandon mid-turn.
    - crashed       : mort SANS clôture prouvée (close_reason crash, close_reason vide sans
                      final_answer, ou run work abandonné en plein tour).

    `agent` : la fiche déjà chargée par l'appelant (sinon relue sur disque). L'arbre et la vue
    du Bureau classent des centaines d'agents qu'ils viennent de lister : relire chaque fiche
    coûtait 727 lectures de fichier par `/api/inbox` à froid."""
    agent_id = str((run or {}).get("agent_id", "") or "")
    if not agent_id:
        return "crashed"
    if runs_distants.est_distant(run):  # execution Rundeck : lue sur le run, jamais un process
        return runs_distants.vivacite(run)
    if agent is None:
        agent = agent_fiche.load_agent(agent_id)
    if agent is None:
        return MISSING
    # `store.agent_status` est la SEULE source qui croise pid + IPC + question pendante
    # sur disque : on la relit plutôt que de recopier ici une 2e règle d'attente, qui
    # dériverait (c'est exactement ce qui rendait l'attente invisible côté flotte).
    state = store.agent_status(agent).get("state")
    if state in ("awaiting_input", "awaiting_plan_validation"):
        return AWAITING
    if state == IDLE:
        # Chaud mais oisif : lu sur la MÊME source que l'attente, jamais redérivé ici.
        return IDLE
    if agent_vivacite.is_running(agent):
        return "running"

    return _issue_d_un_run_mort(agent_id, agent, run)


def _issue_d_un_run_mort(agent_id: str, agent, run: dict) -> str:
    """'delivered' si la clôture lue sur disque prouve une livraison (`issue_de_fin`), ou si le
    ticket de l'agent a été intégré depuis (tué après le merge) ; 'crashed' sinon."""
    data = _session_data(agent_id, agent)
    issue, _code = close_reasons.issue_de_fin(data.get("close_reason") or "",
                                              bool(data.get("final_answer")))
    if issue == "delivered" or travail_integre(agent):
        return "delivered"
    return "crashed"


def travail_integre(agent) -> bool:
    """Le ticket de l'agent a-t-il été intégré (clos par un merge) ? Lit `ticket.state`."""
    slug = str(getattr(agent, "ticket_slug", "") or "")
    ticket_id = str(getattr(agent, "ticket_id", "") or "")
    if not (slug and ticket_id):
        return False
    from . import etat_ticket, tickets
    return etat_ticket.integre(tickets.get_ticket(slug, ticket_id) or {})


def classify_agent(agent) -> str:
    """Vivacité d'un agent CHARGÉ, hors chaîne d'intégration :
    'running'|'awaiting_input'|'delivered'|'crashed'.

    Mêmes preuves que `classify_agent_run` (ticket vide : l'arbre et le panneau de conversation
    montrent des agents isolés). Existe pour que TOUTES les surfaces — sidebar, panneau de
    détail, liste de tickets — lisent la MÊME vivacité, au lieu que chacune redérive un état à
    partir de `status.state` (« la session est close ») et du returncode."""
    return classify_agent_run({}, {
        "agent_id": agent.agent_id,
        "kind": getattr(agent, "run_kind", "") or "",
        "parent": getattr(agent, "parent", "") or "",
    }, agent=agent)
