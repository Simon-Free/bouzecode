# [desc] Migrations boot idempotentes : store au format L2 (état unique, table runs, journal), runs validate hérités clos. [/desc]
"""Migrations one-shot exécutées au démarrage de create_app().

Chaque migration est IDEMPOTENTE (ré-exécutable sans effet de bord), NON DESTRUCTIVE
(ne supprime jamais d'agent/ticket) et LOGGÉE. Une migration qui échoue ne doit jamais
empêcher le serveur de démarrer (l'appelant l'enveloppe dans un try/except).

L'ancienne `migrate_inflight_tickets` (tickets laissés en vol par la chaîne automatique) a
disparu avec le lot L2 : un tel ticket est désormais `running` d'après la correspondance des
drapeaux, et le watchdog constate au premier tick que son agent n'est plus là.
"""

from __future__ import annotations

import logging

from . import tickets
from .fsm import etats, migration

logger = logging.getLogger(__name__)


def _affiner_par_le_process(ticket: dict, run: dict):
    """Un run resté ouvert dans l'ancien store : ce que dit son VRAI process (au boot)."""
    from . import liveness
    vivacite = liveness.classify_agent_run(ticket, run)
    if vivacite == liveness.AWAITING:
        return etats.AWAITING_INPUT, None
    if vivacite == "delivered":
        return etats.DELIVERED, None
    if vivacite == "crashed":
        return etats.STOPPED, {"code": "crashed", "message": "constaté à la migration"}
    if vivacite == liveness.MISSING:
        return etats.STOPPED, {"code": "introuvable", "message": "fiche d'agent introuvable"}
    return None  # running / idle : le watchdog constatera la fin au premier tick


def migrer_le_store(affiner=_affiner_par_le_process) -> int:
    """Passe le store au format L2 (cf. `fsm/migration.py`). Rend le nombre de tickets migrés."""
    with tickets._tickets_lock, tickets._connect() as conn:
        migres = migration.migrer(conn, affiner)
    if migres:
        logger.info("migrer_le_store: %d ticket(s) passés à l'état unique (lot L2)", migres)
        tickets._perimer_l_arbre()
    return migres


def _clore_les_runs_validate(ticket: dict) -> bool:
    """Marque `completed` les runs `validate*` encore ouverts. Renvoie True si l'un a bougé."""
    changed = False
    for run in ticket.get("runs") or []:
        if (isinstance(run, dict) and str(run.get("kind", "")).startswith("validate")
                and not run.get("completed")):
            run["completed"] = True
            changed = True
    return changed


def migrate_legacy_validate_runs() -> int:
    """Clôt les runs `validate*` hérités du validateur de tickets, retiré du backend (D1) : on
    les lit comme des runs TERMINÉS ordinaires. IDEMPOTENTE, NON DESTRUCTIVE, LOGGÉE. Balaie tout
    le store, archivés compris. Renvoie le nombre de tickets modifiés."""
    migrated = 0
    for slug, ticket in tickets.all_tickets():
        if not any(isinstance(r, dict) and str(r.get("kind", "")).startswith("validate")
                   and not r.get("completed") for r in ticket.get("runs") or []):
            continue
        tickets._mutate(slug, ticket["id"], _clore_les_runs_validate)
        migrated += 1
    if migrated:
        logger.info("migrate_legacy_validate_runs: %d ticket(s) aux runs validate clos", migrated)
    return migrated
