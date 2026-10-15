# [desc] Réveil des parents (managers, assistant du Bureau) quand leurs enfants ont une issue, et clôture d'un manager dont le routage est fini — lu sur `ticket.state`, jamais redérivé. [/desc]
"""Extrait de `wake.py`. `process_wakes` regroupe les tickets par parent, réveille ceux dont les
enfants ont une issue neuve (`runner.continue_agent` + digest) et clôt (transition `closed`) le
ticket d'un manager dont tous les enfants ont fini — sous le garde-fou de clôture.
L'idempotence des réveils tient dans `wake.WAKE_STATE_PATH` (dernière signature par parent)."""
from __future__ import annotations

import logging
from pathlib import Path

from ...runtime.runner import agent_fiche, agent_reprise
from ..sessions import store
from . import arret, closure_guard, projects, signalements, ticket_fsm
from . import tickets as tickets_svc
from . import wake, wake_assistant
from .digest_manager import digest_du_manager
from .fsm import etats

_log = logging.getLogger(__name__)

def _groupe_calme(kids: list[dict], signature_connue: str | None) -> bool:
    """Aucun réveil en attente pour ce parent : aucun enfant en vol, signature déjà vue."""
    if any(t.get("state") in etats.ACTIFS for t in kids):
        return False
    return signature_connue == wake.children_signature(kids)


def _children_by_parent(etat_des_reveils: dict | None = None) -> dict[str, list[dict]]:
    """Les tickets (tous projets) regroupés par manager parent. Un groupe calme dont le
    ticket du parent est clos est écarté : il n'a plus aucun réveil en attente."""
    par_parent: dict[str, list[dict]] = {}
    parents_clos: set[str] = set()
    for project in projects.list_projects():
        try:
            rows = tickets_svc.list_tickets(project["slug"])
        except Exception:  # noqa: BLE001 — un projet cassé ne tue pas le regroupement
            _log.exception("wake._children_by_parent: projet %s a échoué", project.get("slug"))
            continue
        parents_clos |= {r.get("agent_id") for t in rows if t.get("state") in etats.CLOS
                         for r in t.get("runs") or [] if isinstance(r, dict)}
        for ticket in rows:
            if wake.is_manager_parent(ticket.get("parent") or ""):
                par_parent.setdefault(ticket["parent"], []).append(ticket)
    return {p: kids for p, kids in par_parent.items()
            if not (p in parents_clos and etat_des_reveils is not None
                    and _groupe_calme(kids, etat_des_reveils.get(p)))}


def _finalize_noncoding_parent(parent_agent, kids: list[dict] | None = None) -> bool:
    """Clôt (transition `closed`) le ticket LIVRÉ d'un manager/monitor dont le routage est
    fini : sans ça il resterait « à vérifier » à vie. Jamais un ticket planté (le crash reste
    visible), jamais par-dessus le garde-fou de clôture (un enfant n'a rien livré)."""
    slug, tid = parent_agent.ticket_slug, parent_agent.ticket_id
    if not (slug and tid):
        return False
    ticket = tickets_svc.get_ticket(slug, tid)
    if ticket is None or ticket.get("state") != etats.DELIVERED:
        return False
    if (ticket.get("typology") or "") not in wake.NON_CODING_TYPOLOGIES:
        return False
    if closure_guard.refuse_closure(slug, ticket, list(kids or ())):
        return False
    ticket_fsm.appliquer(slug, tid, etats.CLOSE, "watchdog", code="routage_termine",
                         message="tous les enfants ont rendu leur issue")
    return True


def _routage_fini(parent_finished: bool, kids: list[dict], deja_signe: bool) -> bool:
    if not (parent_finished and deja_signe) or any(wake.child_pending_launch(t) for t in kids):
        return False
    comptent = [t for t in kids if wake.child_counts_for_wake(t)]
    return bool(comptent) and all(wake.ticket_terminal(t) for t in comptent)


_dead_cwd_parents: set[str] = set()


def _parent_utilisable(parent_id: str):
    """L'agent parent, ou None s'il est introuvable ou si son worktree a disparu."""
    parent_agent = agent_fiche.load_agent(parent_id)
    if parent_agent is None:
        return None
    if parent_agent.cwd and not Path(parent_agent.cwd).is_dir():
        _log.warning("wake: parent %s a un cwd disparu (%s) — ignoré désormais", parent_id,
                     parent_agent.cwd)
        _dead_cwd_parents.add(parent_id)
        return None
    return parent_agent


def _ticket_du(agent) -> tuple[str, dict | None]:
    slug = getattr(agent, "ticket_slug", "")
    ticket_id = getattr(agent, "ticket_id", "")
    return slug, (tickets_svc.get_ticket(slug, ticket_id) if slug and ticket_id else None)


def _reveil_sans_objet(parent_agent) -> str:
    """Pourquoi ce parent ne doit PAS être relancé ("" = le réveil a lieu) : un arrêt demandé
    (journal du ticket), ou un ENFANT d'agent qui a clos sans attendre d'enfant."""
    slug, ticket = _ticket_du(parent_agent)
    if arret.demande(ticket, slug):
        return "arrêt demandé"
    if not wake.is_manager_parent((ticket or {}).get("parent") or ""):
        return ""
    session = getattr(parent_agent, "session_path", "")
    data = store.load_session_json(Path(session)) if session else None
    if (data or {}).get("cloture_en_attente_des_enfants") is False:
        return "clos sans attendre d'enfant"
    return ""


def _noter_sans_relancer(parent_agent, kids: list[dict], motif: str) -> None:
    """Le compte rendu reste LISIBLE sans relancer le travail : au journal du parent."""
    slug, ticket = _ticket_du(parent_agent)
    if ticket is None:
        return
    lus = [{"ticket": t["id"], "issue": wake.ticket_outcome(t)} for t in kids
           if wake.child_counts_for_wake(t)]
    tickets_svc._mutate(slug, ticket["id"],
                        lambda frais: frais.__setitem__("comptes_rendus_sans_relance", lus))
    tickets_svc.add_comment(slug, ticket, f"Réveil évité ({motif}) — comptes rendus de ses "
                            "enfants notés sans relancer l'agent : "
                            + " ; ".join(f"{x['ticket']} : {x['issue']}" for x in lus), False)


_TOUR_CLOS = frozenset({"finished", "idle"})


def _traiter_parent(parent_id: str, kids: list[dict], state: dict) -> bool:
    """Réveille le parent si ses enfants ont bougé ; le clôt si tout est fini. True = réveillé."""
    parent_agent = _parent_utilisable(parent_id)
    if parent_agent is None:
        return False
    etat = store.agent_status(parent_agent)["state"]
    if wake_assistant.est_assistant(parent_agent):
        return wake_assistant.traiter(parent_agent, kids, state, etat in _TOUR_CLOS)
    signature = wake.children_signature(kids)
    if wake.should_wake_parent(etat in _TOUR_CLOS, kids, state.get(parent_id), signature):
        state[parent_id] = signature
        motif = _reveil_sans_objet(parent_agent)
        if motif:
            _noter_sans_relancer(parent_agent, kids, motif)
            _log.info("wake: %s non relancé (%s)", parent_id, motif)
            return False
        agent_reprise.continue_agent(parent_agent, digest_du_manager(kids)
                              + signalements.digest_pour(parent_id))
        return True
    if _routage_fini(etat == "finished", kids, state.get(parent_id) == signature):
        _finalize_noncoding_parent(parent_agent, kids)
    return False


def process_wakes() -> list[str]:
    """Réveille les parents dont les enfants ont une issue neuve. Rend les agent_id réveillés."""
    state = wake._load_wake_state()
    avant = dict(state)
    woken: list[str] = []
    for parent_id, kids in _children_by_parent(state).items():
        if parent_id in _dead_cwd_parents:
            continue
        try:  # un parent cassé ne fait jamais tomber tout le tick
            if _traiter_parent(parent_id, kids, state):
                woken.append(parent_id)
        except Exception:  # noqa: BLE001 — loggé, jamais avalé en silence
            _log.exception("wake.process_wakes: parent %s a échoué", parent_id)
    if state != avant:
        wake._save_wake_state(state)
    return woken
