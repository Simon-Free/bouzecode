# [desc] Réveil du manager parent quand ses enfants ont fini + WATCHDOG OBSERVATEUR : il CONSTATE (constats → ticket_fsm) et réveille, sans jamais décider. [/desc]
"""Réveil des managers + watchdog observateur (spec ticketing §5.7, principe B4).

Le serveur ne valide, ne merge, ne commite, ne relance et ne ré-isole rien de lui-même : il
SIGNALE, le manager ou l'humain décide. Ce module :
  * lit l'issue d'un enfant dans `ticket.state` — prédicats PURS (`ticket_terminal`,
    `ticket_outcome`, `children_signature`, `should_wake_parent`), aucune redérivation ;
  * joue le WATCHDOG (`tick`, toutes les 8 s, serveur de référence) : pour chaque ticket en
    vol, `constats.constater` traduit ce qu'il observe (question, fin de run, process mort,
    lancement figé) en transitions de `ticket_fsm` ; `conflits` constate un conflit résolu ;
    `reaper` fauche un ticket intégré ; puis les parents sont réveillés (`wake_parents`)."""
from __future__ import annotations
from bouzecode.paths import data_dir as bouzecode_data_dir

import json
import logging
import threading
import time
from pathlib import Path

from ..sessions import store  # noqa: F401 — point d'accroche des tests (wake.store)
from . import conflits, constats, etat_ticket, projects, reaper, tick_annexes
from . import tickets as tickets_svc
from .fsm import etats
from .wake_parents import (  # noqa: F401 — ré-export : API historique de `wake`
    _children_by_parent,
    _finalize_noncoding_parent,
    _reveil_sans_objet,
    process_wakes,
)
from .wake_predicats import (  # noqa: F401 — ré-export : API historique de `wake`
    is_manager_parent,
    _work_run,
    work_delivered,
    launch_failed,
    launch_failure_label,
    ticket_terminal,
    _issue_arretee,
    ticket_outcome,
    has_launched,
    child_counts_for_wake,
    child_pending_launch,
    child_blocked_on_question,
    children_signature,
    should_wake_parent,
    build_wake_digest,
)

_log = logging.getLogger(__name__)

_POLL_INTERVAL = 8  # secondes entre deux ticks du watchdog
WAKE_STATE_PATH = bouzecode_data_dir() / "web_v2" / "wake_state.json"
NON_CODING_TYPOLOGIES = constats.NON_CODING_TYPOLOGIES


# ── État persistant des réveils (idempotence) ───────────────────────────────────

def _load_wake_state() -> dict:
    if not WAKE_STATE_PATH.is_file():
        return {}
    try:
        data = json.loads(WAKE_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_wake_state(state: dict) -> None:
    WAKE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = WAKE_STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(WAKE_STATE_PATH)


# ── Watchdog ────────────────────────────────────────────────────────────────────

def ticket_needs_watchdog(ticket: dict) -> bool:
    """Le watchdog a-t-il quelque chose à constater sur ce ticket ? Pur, zéro I/O : un run en
    vol (ou un lancement), un conflit dont on guette la résolution, un ticket intégré à faucher."""
    if constats.a_constater(ticket):
        return True
    if ticket.get("state") == etats.CONFLICT and etat_ticket.code_raison(ticket) != "conflit_resolu":
        return True
    return reaper.should_reap(ticket)


def _constater_le_projet(slug: str, rows: list[dict]) -> None:
    """Un passage par ticket retenu ; résilient par ticket (jamais silencieux)."""
    for ticket in rows:
        try:
            constats.constater(slug, ticket)
            conflits.observer_resolution(slug, ticket)
            frais = tickets_svc.get_ticket(slug, ticket["id"])
            if frais is not None:
                reaper.reap_ticket(slug, frais)
        except Exception:  # noqa: BLE001 — résilience par ticket, jamais silencieuse
            _log.exception("wake.tick: ticket %s du projet %s a échoué", ticket.get("id"), slug)


def tick() -> None:
    """Un cycle du WATCHDOG OBSERVATEUR : constate, réveille, livre la file de messages, draine
    les vérifications différées, puis les gestes globaux (`tick_annexes`). Un projet sans ticket en vol ne coûte qu'une lecture
    du store : aucun fichier d'agent, aucune session n'est ouvert."""
    for project in projects.list_projects():
        slug = project["slug"]
        try:
            pending = [t for t in tickets_svc.list_tickets(slug) if ticket_needs_watchdog(t)]
            if not pending:
                continue
            from .distant import suivi as suivi_distant  # import local : suivi importe wake
            suivi_distant.suivre_tickets(slug, pending)  # exécutions Rundeck : cadence ≥ 30 s
            _constater_le_projet(slug, pending)
        except Exception:  # noqa: BLE001 — un projet cassé ne tue pas le cycle
            _log.exception("wake.tick: projet %s a échoué", project.get("slug"))
    process_wakes()
    try:
        from . import file_messages
        file_messages.livrer_prets()
    except Exception:  # noqa: BLE001 — une file cassée ne tue pas le cycle
        _log.exception("wake.tick: livraison des messages en file a échoué")
    tick_annexes.balayer_le_pool_chaud()
    try:
        tick_annexes.drainer_les_verifications_differees()
    except Exception:  # noqa: BLE001 — un drain qui échoue ne tue pas le cycle
        _log.exception("wake.tick: drain des vérifications différées a échoué")
    tick_annexes.rattraper_le_bureau()


_poller_started = False
_poller_lock = threading.Lock()


def start_poller(interval: int = _POLL_INTERVAL) -> None:
    """WATCHDOG serveur, ACTIF PAR DÉFAUT (opt-out BOUZECODE_WAKE_POLLER=0), sur le seul
    serveur de référence : c'est le chemin nominal des CRASHES et des fins sans hook."""
    import os
    global _poller_started
    if os.environ.get("BOUZECODE_WAKE_POLLER") == "0":
        return
    from ... import reference  # seul le serveur de référence agit seul sur la flotte
    if not reference.est_reference():
        _log.warning("wake: instance PASSIVE (pas serveur de référence) — watchdog non démarré")
        return
    with _poller_lock:
        if _poller_started:
            return
        _poller_started = True

    def _loop() -> None:
        while True:
            time.sleep(interval)
            try:
                tick()
            except Exception:  # noqa: BLE001 — un poller ne doit jamais mourir
                _log.exception("wake.tick a échoué")

    threading.Thread(target=_loop, daemon=True, name="wake-poller").start()
