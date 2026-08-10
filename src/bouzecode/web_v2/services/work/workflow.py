# [desc] Machine à états DÉCLARATIVE réduite au SIGNALEMENT DE CRASH d'un run (plus aucune chaîne automatique). [/desc]
"""Signalement des crashes d'un ticket, via une TABLE DE TRANSITIONS déclarée.

La chaîne automatique travail→validation→merge A ÉTÉ RETIRÉE (cf.
`docs/design_p10_orchestration.md`) : plus de test-gate, plus de spawn automatique
de validateur, plus de boucle de rework, plus de merge automatique. Le manager (ou
l'utilisateur) décide de chaque étape ; l'intégration passe désormais UNIQUEMENT par
`POST /api/tickets/<slug>/<id>/integrate`.

Ce qui reste ici est le GARDE-FOU ANTI-PERTE, indépendant de toute décision :

  état=work_done  , is_crash → report_crash → crashed
  état=validating , is_crash → report_crash → crashed

Un agent dont le process meurt sans clôture ne se signale par définition pas
lui-même ; sans ces deux transitions il resterait « en cours » pour toujours dans
l'UI et son WIP non commité serait perdu avec le worktree.

Invariants conservés :
  * L'état courant est DÉRIVÉ de l'état persisté du ticket (runs), jamais d'une
    variable mémoire. `done_agent` (l'agent qui vient de finir) est traité comme
    terminé même si son process n'a pas encore quitté.
  * Idempotence : aucune transition ne matche → no-op ; un crash déjà signalé ne
    l'est jamais deux fois."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from . import delivery, tickets

# Sérialisation de advance PAR TICKET : advance est un check-then-act (dérive l'état →
# tire LA transition). Il est appelé concurremment par 3 sources (hook on_completion,
# watchdog, poll de la liste). Sans verrou, deux advance simultanés lisent le MÊME état
# pré-transition et tirent 2× la même action (TOCTOU). Un verrou par id + relecture
# FRAÎCHE du ticket sous verrou rend la transition atomique.
_advance_locks: dict[str, threading.Lock] = {}
_advance_locks_guard = threading.Lock()


def _lock_for(ticket_id: str) -> threading.Lock:
    with _advance_locks_guard:
        lock = _advance_locks.get(ticket_id)
        if lock is None:
            lock = _advance_locks[ticket_id] = threading.Lock()
        return lock


# Champs de run posés HORS du store : `pid_alive` stampé par le reconciler (entrée impure de
# la garde is_crash) et `state`/`key` attachés à la LECTURE par `tickets._attach_run_state`
# (une lecture du fichier agent par run). Ils n'existent que dans le snapshot de l'appelant.
_TRANSIENT_RUN_FIELDS = ("pid_alive", "state", "key")


def _carry_transient(src: dict, dst: dict) -> None:
    """Reporte les champs transitoires des runs du ticket appelant vers la version fraîche
    relue du disque, run-à-run par agent_id.

    Sans ce report, `advance` remplace le snapshot de l'appelant (`ticket.clear()`) par une
    version relue qui a PERDU l'état live tout juste attaché : la route liste annonçait alors
    « à relire » un agent qui TOURNE encore, en contradiction avec sa propre vivacité et avec
    la route de détail. On ne relit JAMAIS `state` du store comme s'il était frais : on ne fait
    que préserver celui que l'appelant vient d'attacher."""
    carried = {
        r.get("agent_id"): {k: r[k] for k in _TRANSIENT_RUN_FIELDS if k in r}
        for r in src.get("runs") or [] if isinstance(r, dict)
    }
    for run in dst.get("runs") or []:
        if isinstance(run, dict) and carried.get(run.get("agent_id")):
            run.update(carried[run["agent_id"]])

# `idle` (warm pool : process résident, tour fini) compte comme ACTIF. Le retirer ferait
# basculer `derive_state` de `busy` à libre dès la fin d'un tour, donc rouvrirait la
# fenêtre de spawn prématuré du validateur pendant qu'un agent chaud peut encore recevoir
# du travail. La distinction `idle`/`running` sert la JOIGNABILITÉ et l'affichage ; elle
# ne doit rien changer aux chaînes de décision du ticket.
_ACTIVE = ("running", "starting", "awaiting_input", "awaiting_plan_validation", "idle")

# Typologies read-only (routeur/observateur) : elles ne PRODUISENT aucun diff. Plus aucune
# chaîne ne les concerne, mais le libellé de statut et le réveil du parent s'en servent
# encore (cf. `tickets.derive_status`, `wake._finalize_noncoding_parent`).
NON_CODING_TYPOLOGIES = frozenset({"manager", "monitor"})


# ── Dérivation de l'état (depuis le ticket persisté) ──────────────────────────

def _run_active(run: dict, done_agent: str) -> bool:
    return (run.get("agent_id") != done_agent
            and run.get("state") in _ACTIVE)


def derive_state(ticket: dict, done_agent: str = "") -> str:
    """État courant du workflow, dérivé des runs (pur)."""
    meta = ticket.get("worktree")
    if isinstance(meta, dict) and meta.get("state") in ("integrated", "cleaned"):
        return "done"
    # Merge demandé mais BLOQUÉ (arbre principal sale ou conflit non auto-résolu) : PARKÉ.
    # Aucune transition ne matche 'needs_attention' → advance() no-op. Re-tentable via
    # POST /integrate quand l'arbre redevient propre (worktree conservé, cf. reaper).
    if isinstance(meta, dict) and meta.get("state") == "needs_attention":
        return "needs_attention"
    # Éphémère déjà finalisé (auto-reap) : terminal même sans worktree (projet non-git).
    if ticket.get("ephemeral") and ticket.get("reaped"):
        return "done"
    # Crash DÉJÀ signalé : état terminal, plus aucune transition.
    if ticket.get("crashed"):
        return "crashed"
    runs = [r for r in ticket.get("runs") or [] if isinstance(r, dict)]
    if any(_run_active(r, done_agent) for r in runs):
        return "busy"
    if not runs:
        return "idle"
    kind = str(runs[0].get("kind", ""))
    if kind == "work":
        return "work_done"
    if kind.startswith("validate"):
        return "validating"
    return "idle"  # merge/conflit ou forme inconnue


# ── Gardes (pures, sur le ticket) ─────────────────────────────────────────────

def _is_crash(ticket: dict) -> bool:
    """CRASH (pur) : le run le plus récent a son process MORT (`pid_alive` stampé False
    par le watchdog) sans avoir été `completed` (aucun hook on_completion) ni rendu de
    verdict — agent tombé sans clôture gracieuse. `pid_alive` absent (None) → jamais un
    crash (les chemins push /completed et la route liste ne le stampent pas)."""
    newest = next((r for r in ticket.get("runs") or [] if isinstance(r, dict)), None)
    if newest is None or newest.get("completed") or newest.get("verdict"):
        return False
    return newest.get("pid_alive") is False


GUARDS: dict[str, Callable[[dict], bool]] = {
    "is_crash": _is_crash,
    # Livraison propre (run `completed`) dont le worktree n'a pas encore été récolté.
    # Pure, et FAUSSE dès la première récolte : rejouer la chaîne ne recommite rien.
    "delivery_unharvested": delivery.needs_delivery_harvest,
}


# ── Actions (effets) ──────────────────────────────────────────────────────────

def _harvest_wip(meta, ticket: dict) -> None:
    """Récolte best-effort du travail non commité DANS le worktree agent AVANT de
    signaler le crash. harvest est idempotent (status --porcelain vide → no-op).
    JAMAIS propager d'erreur — le harvest ne doit pas empêcher le crash-report ; à
    défaut, l'ancien comportement (WIP perdu) reste la pire issue."""
    if not isinstance(meta, dict) or not meta.get("worktree"):
        return
    try:
        from . import worktrees
        worktrees.harvest(meta, ticket.get("title", ""))
    except Exception:
        pass  # best-effort : l'échec de harvest ne doit jamais interrompre la transition


def _act_report_crash(slug: str, ticket: dict, done_agent: str) -> None:
    """CRASH détecté par le watchdog : marque le ticket en statut VISIBLE `crashed`
    (persistant → UI + digest parent) et réveille le parent. IDEMPOTENT (déjà `crashed`
    → no-op, pas de double-report). Ne merge JAMAIS. Marqué → derive_state="crashed"
    (terminal), donc le parent peut être réveillé (tous enfants terminaux)."""
    if ticket.get("crashed"):
        return  # déjà signalé — idempotent
    from . import tickets as tickets_svc, wake
    # Récolte best-effort avant de marquer crashed : le WIP d'un codeur crashé finit
    # commité sur sa branche agent (récupérable) au lieu d'être perdu avec le worktree.
    _harvest_wip(ticket.get("worktree"), ticket)
    ticket["crashed"] = True
    for run in ticket.get("runs") or []:  # pid_alive = transitoire (reconciler), pas persisté
        if isinstance(run, dict):
            run.pop("pid_alive", None)
    tickets_svc.update_ticket(slug, ticket)
    wake.process_wakes()


ACTIONS: dict[str, Callable[[str, dict, str], None]] = {
    "report_crash": _act_report_crash,
    "harvest_delivery": delivery.harvest_delivery,
}


# ── Table de transitions (lisible d'un coup d'œil ; un plugin pourra fournir la sienne) ──

@dataclass(frozen=True)
class Transition:
    state: str            # état courant requis
    guard: str | None     # nom d'une garde dans GUARDS, ou None (toujours vrai)
    action: str           # nom d'une action dans ACTIONS
    next: str             # état résultant


TRANSITIONS: list[Transition] = [
    # Un run work/validate dont le process est mort sans clôture (`pid_alive` False, ni
    # completed ni verdict) est signalé au parent et le ticket passe `crashed`. Elle ne
    # décide de rien, elle observe. En TÊTE : un run mort n'est jamais une livraison.
    Transition("work_done", "is_crash", "report_crash", "crashed"),
    Transition("validating", "is_crash", "report_crash", "crashed"),
    # Le codeur a fini PROPREMENT : son travail est commité sur sa branche. Ce n'est pas
    # une reprise de la chaîne travail→validation→merge (rien n'est validé ni mergé) mais
    # l'autre moitié du filet anti-perte : jusqu'ici seul un agent qui CRASHAIT voyait son
    # WIP sauvé, un agent qui RÉUSSISSAIT le laissait dans un worktree fauchable.
    Transition("work_done", "delivery_unharvested", "harvest_delivery", "delivered"),
]


def _matching_transition(ticket: dict, done_agent: str) -> Transition | None:
    state = derive_state(ticket, done_agent)
    for tr in TRANSITIONS:
        if tr.state != state:
            continue
        if tr.guard is None or GUARDS[tr.guard](ticket):
            return tr
    return None


def _advance_once(slug: str, ticket: dict, done_agent: str,
                  table: list[Transition]) -> str | None:
    state = derive_state(ticket, done_agent)
    for tr in table:
        if tr.state != state:
            continue
        if tr.guard is None or GUARDS[tr.guard](ticket):
            ACTIONS[tr.action](slug, ticket, done_agent)
            return tr.next
    return None


def advance(slug: str, ticket: dict, done_agent: str = "",
            transitions: list[Transition] | None = None) -> str | None:
    """Applique LA transition qui matche (état, garde) → exécute son action → renvoie
    l'état suivant. Aucune transition ne matche → None (no-op). Générique : la table
    est un paramètre (un plugin peut fournir la sienne).

    ATOMIQUE PAR TICKET : sous le verrou de l'id, on relit le ticket FRAIS du disque (les
    appels concurrents partagent sinon un snapshot périmé → double transition). On reporte
    les champs transitoires (pid_alive) du snapshot appelant sur la version fraîche."""
    table = transitions if transitions is not None else TRANSITIONS
    ticket_id = ticket.get("id")
    if not ticket_id:
        return _advance_once(slug, ticket, done_agent, table)
    with _lock_for(ticket_id):
        fresh = tickets.get_ticket(slug, ticket_id)
        if fresh is None:
            return _advance_once(slug, ticket, done_agent, table)
        _carry_transient(ticket, fresh)
        result = _advance_once(slug, fresh, done_agent, table)
        if fresh is not ticket:  # refléter les mutations de l'action sur l'objet appelant
            ticket.clear()
            ticket.update(fresh)
        return result


def is_terminal(ticket: dict, done_agent: str = "") -> bool:
    """Vrai quand rien ne tourne et qu'aucune transition n'est en attente pour ce
    ticket. Sert au calcul de réveil du parent."""
    if derive_state(ticket, done_agent) == "busy":
        return False
    return _matching_transition(ticket, done_agent) is None
