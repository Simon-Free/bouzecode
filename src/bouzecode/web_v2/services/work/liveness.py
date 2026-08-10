"""Classification UNIFIÉE, dérivée de PREUVES, de l'état vivant/mort d'un run et
d'un ticket. Source unique de vérité pour distinguer un agent/ticket qui TOURNE
ENCORE, qui a LIVRÉ proprement, qui a CRASHÉ (à relancer à la main), ou qui est
resté COINCÉ (fini mais chaîne d'intégration non aboutie).

Ce module NE déclenche AUCUNE reprise automatique : il OBSERVE et CLASSIFIE.

Pourquoi croiser plusieurs preuves plutôt qu'un seul champ close_reason ?
- close_reason peut être VIDE sur des sessions historiques (le stamp a manqué sur
  certains chemins de clôture) → on tolère cela via la présence d'un final_answer
  ou d'un verdict de run.
- returncode == -1 ne couvre PAS tous les morts (un agent tué au restart peut avoir
  un rc stampé autrement, ou un enregistrement disparu) → on croise pid + session.

Réutilise SANS dupliquer les prédicats d'autorité existants :
- runner.is_running / load_agent (preuve PID)
- store.load_session_json (close_reason / final_answer disque = fait autorité)
- wake.GRACEFUL_CLOSE_REASONS + wake._is_work_abandoned_mid_turn
- wake.work_delivered + reaper.terminal_outcome + workflow.derive_state
"""
from __future__ import annotations

from pathlib import Path

from ... import close_reasons
from ...runtime import runner
from ..sessions import store
from . import delivery, reaper, wake, workflow

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
        session_path = str(runner.AGENTS_DIR / f"{agent_id}.session.json")
    return Path(session_path)


def _session_data(agent_id: str, agent) -> dict:
    return store.load_session_json(_session_path(agent_id, agent)) or {}


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


def classify_agent_run(ticket: dict, run: dict) -> str:
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
                      présent, OU verdict de run) — hors abandon mid-turn.
    - crashed       : mort SANS clôture prouvée (close_reason crash, close_reason vide sans
                      final_answer/verdict, ou run work abandonné en plein tour)."""
    agent_id = str((run or {}).get("agent_id", "") or "")
    if not agent_id:
        return "crashed"
    agent = runner.load_agent(agent_id)
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
    if runner.is_running(agent):
        return "running"

    data = _session_data(agent_id, agent)
    close_reason = data.get("close_reason") or ""
    final_answer = data.get("final_answer") or ""
    verdict = (run or {}).get("verdict") or ""

    # Un run WORK clos sur text_no_tools = arrêté en plein milieu (aucune FinalAnswer) :
    # CRASH fonctionnel, jamais une livraison — testé AVANT la branche clean (text_no_tools
    # ∈ GRACEFUL, donc ∈ CLEAN : ce filtre doit primer pour les runs work).
    if wake._is_work_abandoned_mid_turn(run, close_reason):
        return "crashed"
    if close_reason in CRASH_CLOSE_REASONS:
        return "crashed"
    if close_reason in CLEAN_CLOSE_REASONS or final_answer or verdict:
        return "delivered"
    # Mort sans clôture stampée, sans final_answer, sans verdict → crash silencieux
    # (cas 5 : la mort au restart n'a laissé AUCUNE trace de fin propre).
    return "crashed"


def run_verdict(agent, state: str) -> str:
    """Verdict lisible d'un run `validate` TERMINÉ : rc=0 → 'OK', rc≠0 → 'KO'. Vide sinon.

    UNE seule définition, partagée par le node de l'arbre (`fleet._node`), par le panneau de
    conversation et par `classify_agent` : deux surfaces ne peuvent plus dériver deux verdicts
    différents du même agent."""
    if (getattr(agent, "run_kind", "") or "") != "validate" or state != "finished":
        return ""
    return "OK" if agent.returncode == 0 else "KO"


def classify_agent(agent, state: str) -> str:
    """Vivacité d'un agent CHARGÉ, hors chaîne d'intégration :
    'running'|'awaiting_input'|'delivered'|'crashed'.

    Mêmes preuves que `classify_agent_run` (ticket vide : l'arbre et le panneau de conversation
    montrent des agents isolés). Existe pour que TOUTES les surfaces — sidebar, panneau de
    détail, liste de tickets — lisent la MÊME vivacité, au lieu que chacune redérive un état à
    partir de `status.state` (« la session est close ») et du returncode."""
    return classify_agent_run({}, {
        "agent_id": agent.agent_id,
        "kind": getattr(agent, "run_kind", "") or "",
        "verdict": run_verdict(agent, state),
        "parent": getattr(agent, "parent", "") or "",
    })


def _classifiable_runs(ticket: dict) -> list[dict]:
    return [r for r in (ticket.get("runs") or [])
            if isinstance(r, dict) and r.get("agent_id")
            and (str(r.get("kind", "")) == "work"
                 or str(r.get("kind", "")).startswith("validate"))]


def classify_ticket(ticket: dict) -> str:
    """Classe un TICKET : 'running' | 'awaiting_input' | 'missing' | 'delivered'
    | 'awaiting_decision' | 'stalled' | 'crashed' | 'launching'.

    - launching        : en cours de lancement (spawn différé) sans aucun run démarré.
    - running          : au moins un run encore vivant.
    - awaiting_input   : un run attend une réponse de l'utilisateur.
    - missing          : ANOMALIE D'INVENTAIRE. Le ticket est OUVERT et référence un agent
                         dont l'enregistrement n'existe plus : il est injoignable (tout
                         message vers lui échoue) et sa fiche est à restaurer. Un ticket
                         CLOS garde `crashed`/`delivered` : la fiche d'un agent rangé après
                         coup a le droit d'avoir disparu.
    - awaiting_decision: le codeur a LIVRÉ (travail commité sur sa branche) et aucune issue
                         terminale n'a été décidée. Depuis le retrait de la chaîne
                         automatique c'est l'issue NORMALE de tout ticket : quelqu'un doit
                         choisir entre relancer, valider ou intégrer.
    - delivered        : issue terminale prouvée (mergé/verdict/parké) — livraison actée.
    - stalled          : ANOMALIE. Le run a livré mais son travail n'est commité NULLE PART
                         (`delivery.delivery_at_risk`) : une perte silencieuse est possible,
                         il faut intervenir.
    - crashed          : mort sans clôture prouvée.

    POURQUOI CE DÉCOUPAGE : `stalled` couvrait AUSSI l'attente de décision. Le board
    annonçait donc « stalled » — lu comme « planté » — pendant que `/api/agents/tree`
    annonçait « delivered » pour le MÊME instant (cas vécu 28/07, tickets a88aeb4c /
    e03adb3b). Les deux vues répondaient à deux questions sous le même mot. `stalled` ne
    désigne plus qu'un ticket qui a RÉELLEMENT quelque chose à perdre."""
    runs = _classifiable_runs(ticket)
    if ticket.get("launching") and not runs:
        return "launching"
    if not runs:
        # Ticket sans run classifiable : s'appuyer sur l'état dérivé (idle) — non interrompu.
        return "delivered" if workflow.derive_state(ticket) == "done" else "crashed"

    statuses = [classify_agent_run(ticket, r) for r in runs]
    # Le vocabulaire du TICKET n'a pas de notion de « chaud » : un run oisif est un run
    # dont personne n'a encore décidé le sort et qui repart au premier message — le ticket
    # est donc TOUJOURS en vol. On normalise ici plutôt qu'au niveau du run pour que la
    # distinction serve la joignabilité et l'affichage des AGENTS (arbre, sidebar, panneau)
    # sans rien changer au board : lâcher `idle` dans la suite ferait basculer le ticket en
    # `awaiting_decision`, voire crier `stalled` (« livraison en péril ») sur un codeur qui
    # n'a simplement pas encore commité le travail de son prochain tour.
    statuses = ["running" if s == IDLE else s for s in statuses]
    if AWAITING in statuses:
        # Un run bloqué sur une question ne peut PAS être classé comme livré ni planté :
        # il reprendra dès qu'on lui répond. Il remonte au niveau du ticket pour que le
        # board dise « attend une réponse » au lieu de « en cours » (indiscernable).
        return AWAITING
    if "running" in statuses:
        return "running"
    # `missing` est un RAFFINEMENT STRICT de `crashed`, jamais un état de plus dans le
    # flux normal : on laisse d'abord la classification habituelle se dérouler, et on ne
    # renomme qu'à la toute fin, si elle a conclu « planté ». Un ticket dont le travail
    # est livré/mergé garde donc son état — la fiche d'un agent rangé après coup n'est pas
    # une anomalie. Sans cette précaution, TOUT ticket un peu ancien (agents purgés depuis
    # longtemps) se serait mis à crier « agent introuvable ».
    agent_manquant = MISSING in statuses and not (ticket.get("done") or ticket.get("archived"))
    statuses = ["crashed" if s == MISSING else s for s in statuses]

    outcome = reaper.terminal_outcome(ticket)
    if outcome == "crashed":
        return MISSING if agent_manquant else "crashed"
    if outcome in ("integrated", "failed", "needs_attention"):
        # Issue terminale connue et prouvée (mergé, verdict KO, ou merge parké) : actée.
        return "delivered"

    # Aucune issue terminale : un run livré attend une décision — SAUF si son travail n'est
    # commité nulle part, auquel cas il n'attend pas, il est en péril (`stalled`).
    if "delivered" in statuses:
        return "stalled" if delivery.delivery_at_risk(ticket) else "awaiting_decision"
    return MISSING if agent_manquant else "crashed"
