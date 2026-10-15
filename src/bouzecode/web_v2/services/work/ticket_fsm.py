# [desc] LA machine à états des tickets : `transition` (pure, refuse toute transition non listée), `appliquer` (persistée sous verrou, run + journal dans la même transaction), `motiver`, `events`. [/desc]
"""Un seul état persisté par ticket, écrit par un seul module (spec ticketing §4, B2).

* `transition(ticket, evenement, **data)` — PURE : change `state` / `state_reason` de l'objet
  selon `fsm/etats.TRANSITIONS`, lève `TransitionRefusee` (409 `transition_refusee`, état
  courant dans `details`) pour toute paire absente de la table, `DejaActif` (409 `deja_actif`)
  pour un lancement sur un ticket dont un run est en vol (C10).
* `appliquer(slug, ticket_id, evenement, actor, **data)` — PERSISTÉE : relit le ticket frais,
  applique la transition, met ses runs d'accord (`fsm/cycle_des_runs`), écrit la ligne sous
  condition de version et l'événement du journal, dans UNE transaction. Deux appelants
  concurrents ne peuvent donc pas lancer deux runs : le second lit l'état du premier.
* `motiver(...)` — change `state_reason` sans changer d'état (garde-fou de clôture, récolte…).
* `events(slug, ticket_id, since)` — le journal du ticket.

Données reconnues dans `data` : `code` / `message` / `details` (la raison posée), `delivered`
(fin de run, décidé par `close_reasons.issue_de_fin`), `agent_id` (run visé), `nouveau_run`
(run créé par cette transition), `close_reason` / `final_answer` / `returncode` (le `end` du
run). Tout le reste est seulement journalisé."""
from __future__ import annotations

from bouzecode.web_v2.services.horodatage import maintenant_iso

from ._ligne_ticket import VersionObsolete  # noqa: F401 — ré-export : 409 version_obsolete
from .fsm import cycle_des_runs, etats, journal

#: Rejouer ces gestes sur un ticket déjà arrivé est un no-op (spec §9, « Idempotence »).
_IDEMPOTENTS = frozenset({etats.CLOSE, etats.ABANDON, etats.STOP, etats.CRASHED, etats.REOPENED})


class TransitionRefusee(RuntimeError):
    code = "transition_refusee"

    def __init__(self, ticket: dict, evenement: str):
        state = str(ticket.get("state") or "")
        super().__init__(f"transition refusée : « {evenement} » impossible depuis l'état "
                         f"« {state} » (ticket {ticket.get('id', '?')})")
        self.details = {"state": state, "evenement": evenement,
                        "ticket_id": str(ticket.get("id") or ""),
                        "state_reason": ticket.get("state_reason")}


class DejaActif(TransitionRefusee):
    """Un lancement demandé alors qu'un run (ou un lancement) est déjà en vol (C10)."""
    code = "deja_actif"


def _raison(evenement: str, data: dict) -> dict | None:
    code = data.get("code") or etats.raison_par_defaut(evenement)
    if not code:
        return None
    raison = {"code": str(code), "message": str(data.get("message") or ""), "at": _maintenant()}
    if data.get("details"):
        raison["details"] = data["details"]
    return raison


def _maintenant() -> str:
    return maintenant_iso()


def _sans_date(raison: dict | None) -> dict | None:
    return {k: v for k, v in raison.items() if k != "at"} if isinstance(raison, dict) else raison


def _deja_arrive(ticket: dict, evenement: str) -> bool:
    arrivees = {cible for (_etat, ev), cibles in etats.TRANSITIONS.items() if ev == evenement
                for cible in cibles}
    return evenement in _IDEMPOTENTS and ticket.get("state") in arrivees


def transition(ticket: dict, evenement: str, **data) -> str:
    """Applique `evenement` à l'objet `ticket` (sans rien persister) ; rend le nouvel état."""
    state = str(ticket.get("state") or "")
    a_des_runs = any(isinstance(r, dict) for r in ticket.get("runs") or [])
    arrivee = etats.cible(state, evenement, bool(data.get("delivered", True)), a_des_runs)
    if arrivee is None:
        if evenement == etats.LAUNCHED and state in etats.ACTIFS:
            raise DejaActif(ticket, evenement)
        raise TransitionRefusee(ticket, evenement)
    ticket["state"], ticket["state_reason"] = arrivee, _raison(evenement, data)
    return arrivee


def _journalisable(data: dict) -> dict:
    return {k: v for k, v in data.items() if k not in ("nouveau_run",)} | (
        {"agent_id": data["nouveau_run"].get("agent_id")} if data.get("nouveau_run") else {})


def appliquer(slug: str, ticket_id: str, evenement: str, actor: str = "serveur",
              version: int | None = None, **data) -> dict:
    """Transition PERSISTÉE ; rend le ticket frais. `version` : celle que l'appelant a lue
    (refus `VersionObsolete` si le ticket a bougé). Lève `LookupError` si le ticket n'existe pas."""
    from . import _ligne_ticket, _persistence
    for _essai in range(5):
        with _persistence._tickets_lock, _persistence._connect() as conn:
            frais = _ligne_ticket.lire(conn, slug, ticket_id)
            if frais is None:
                raise LookupError(f"ticket inconnu : {slug}/{ticket_id}")
            if version is not None and frais["version"] != version:
                raise VersionObsolete(slug, ticket_id, version, frais["version"], frais["state"])
            if _deja_arrive(frais, evenement):
                return frais
            depart = frais["state"]
            transition(frais, evenement, **data)
            if frais["state"] != etats.PROVISIONING:
                from .launch_phase import clear_phase  # la phase meurt avec la préparation
                clear_phase(frais)
            try:
                _ligne_ticket.ecrire(conn, slug, frais, version_lue=frais["version"],
                                     etat=(frais["state"], frais["state_reason"]))
            except VersionObsolete:
                conn.rollback()
                continue
            cycle_des_runs.appliquer(conn, slug, frais, depart, frais["state"], evenement,
                                     frais["state_reason"], data)
            journal.ecrire(conn, slug, ticket_id, evenement, actor,
                           {"de": depart, "vers": frais["state"],
                            "raison": frais["state_reason"], **_journalisable(data)})
        _persistence._perimer_l_arbre()
        return frais
    raise VersionObsolete(slug, ticket_id, -1, -1, "?")


def motiver(slug: str, ticket_id: str, code: str | None, message: str = "",
            actor: str = "serveur", **details) -> dict | None:
    """Pose (ou efface, `code=None`) la raison de l'état courant, sans changer d'état."""
    from . import _ligne_ticket, _persistence
    raison = {"code": code, "message": message, **({"details": details} if details else {})} \
        if code else None
    with _persistence._tickets_lock, _persistence._connect() as conn:
        frais = _ligne_ticket.lire(conn, slug, ticket_id)
        if frais is None or _sans_date(frais.get("state_reason")) == raison:
            return frais
        raison = {**raison, "at": _maintenant()} if raison else None
        _ligne_ticket.ecrire(conn, slug, frais, etat=(frais["state"], raison))
        journal.ecrire(conn, slug, ticket_id, journal.MOTIF, actor,
                       {"state": frais["state"], "raison": raison})
    _persistence._perimer_l_arbre()
    return frais


def events(slug: str, ticket_id: str, since: int = 0) -> list[dict]:
    """Le journal du ticket (événements de `seq` > `since`, dans l'ordre)."""
    from . import _persistence
    with _persistence._connect() as conn:
        return journal.lire(conn, slug, ticket_id, since)


def noter(slug: str, ticket_id: str, kind: str, actor: str = "serveur", at: str = "",
          **data) -> int:
    """Ajoute au journal un événement qui ne change pas l'état (commentaire, arrêt demandé…)."""
    from . import _persistence
    with _persistence._tickets_lock, _persistence._connect() as conn:
        seq = journal.ecrire(conn, slug, ticket_id, kind, actor, data, at=at)
    _persistence._perimer_l_arbre()
    return seq
