# [desc] Ce qu'une transition du ticket fait à ses runs : run courant, run neuf, fin de run (`end`), état du run (starting/running/awaiting_input/awaiting_children/ended). [/desc]
"""L'état d'un run suit celui de son ticket (spec §3.2) : il n'est écrit QUE par la transition
du ticket, dans la même transaction. Invariant tenu ici : un ticket `running` ou
`awaiting_input` a exactement un run non terminé ; tout autre état n'en a aucun."""
from __future__ import annotations

from bouzecode.web_v2.services.horodatage import maintenant_iso

from . import etats, stockage

RUN_RUNNING, RUN_AWAITING_INPUT = "running", "awaiting_input"
RUN_AWAITING_CHILDREN, RUN_ENDED = "awaiting_children", "ended"


def _maintenant() -> str:
    return maintenant_iso()


def run_courant(ticket: dict, agent_id: str = "") -> dict | None:
    """Le run visé : celui de `agent_id`, sinon le plus récent qui n'est pas terminé."""
    runs = [r for r in ticket.get("runs") or [] if isinstance(r, dict)]
    if agent_id:
        return next((r for r in runs if r.get("agent_id") == agent_id), None)
    return next((r for r in runs if r.get("state") != RUN_ENDED), None)


def _terminer(conn, run: dict, end: dict) -> None:
    fin = _maintenant()
    stockage.ecrire_etat(conn, run["agent_id"], RUN_ENDED, end, fin)
    run.update(state=RUN_ENDED, end=end, ended_at=fin)


def _ouvrir(conn, run: dict, state: str) -> None:
    stockage.ecrire_etat(conn, run["agent_id"], state, None, None)
    run["state"] = state
    run.pop("ended_at", None)


def _fin(data: dict, raison: dict | None, delivered: bool) -> dict:
    return {"reason": str(data.get("close_reason") or (raison or {}).get("code") or ""),
            "delivered": delivered, "final_answer": bool(data.get("final_answer")),
            "returncode": data.get("returncode")}


def _ajouter(conn, slug: str, ticket: dict, run: dict) -> dict:
    """Pose le run neuf (en tête) ; un run encore ouvert est clos : il est REMPLACÉ."""
    for ancien in [r for r in ticket.get("runs") or [] if r.get("state") != RUN_ENDED]:
        _terminer(conn, ancien, {"reason": "remplace", "delivered": False,
                                 "final_answer": False, "returncode": None})
    run.setdefault("state", RUN_RUNNING)
    run.setdefault("started_at", _maintenant())
    stockage.inserer(conn, slug, ticket["id"], run)
    ticket["runs"] = [run] + [r for r in ticket.get("runs") or []
                              if r.get("agent_id") != run["agent_id"]]
    return run


def appliquer(conn, slug: str, ticket: dict, depart: str, arrivee: str, evenement: str,
              raison: dict | None, data: dict) -> None:
    """Met les runs du ticket en accord avec la transition `depart` → `arrivee`."""
    nouveau = data.get("nouveau_run")
    if nouveau:
        _ajouter(conn, slug, ticket, dict(nouveau))
    run = run_courant(ticket, "" if nouveau else str(data.get("agent_id") or ""))
    if run is None and arrivee in (etats.RUNNING, etats.AWAITING_INPUT):
        run = next((r for r in ticket.get("runs") or [] if isinstance(r, dict)), None)
    if run is None:
        return
    if arrivee == etats.AWAITING_INPUT:
        _ouvrir(conn, run, RUN_AWAITING_INPUT)
    elif evenement == etats.AWAITING_CHILDREN:
        _ouvrir(conn, run, RUN_AWAITING_CHILDREN)
    elif arrivee == etats.RUNNING:
        _ouvrir(conn, run, RUN_RUNNING)
    elif depart in (etats.RUNNING, etats.AWAITING_INPUT) and run.get("state") != RUN_ENDED:
        _terminer(conn, run, _fin(data, raison, arrivee == etats.DELIVERED))
    elif depart == etats.STOPPED and evenement == etats.RUN_ENDED:
        #  Fin tardive qui prouve la livraison : le `end` du run est corrigé, pas rouvert.
        fin = _fin(data, raison, True)
        stockage.ecrire_etat(conn, run["agent_id"], RUN_ENDED, fin, run.get("ended_at") or _maintenant())
        run.update(end=fin)
