# [desc] Migration boot idempotente reparentant les validateurs/auto-merge hérités sous leur codeur (run work). [/desc]
"""Migrations one-shot exécutées au démarrage de create_app().

Chaque migration est IDEMPOTENTE (ré-exécutable sans effet de bord), NON DESTRUCTIVE
(ne supprime jamais d'agent/ticket) et LOGGÉE. Une migration qui échoue ne doit jamais
empêcher le serveur de démarrer (l'appelant l'enveloppe dans un try/except).
"""

from __future__ import annotations

import logging

from ...runtime import runner
from . import projects, tickets

logger = logging.getLogger(__name__)

# Parents littéraux hérités : ces agents (validateur, résolveur de merge) ont été créés
# AVANT le fix 4c8c410 qui les rattache désormais à l'id réel du codeur. Sur disque ils
# portent encore ce texte figé au lieu de l'agent_id du codeur → invisibles dans l'arbre.
_LEGACY_PARENTS = {"dispatcher:validate", "dispatcher:auto-merge"}


def _work_agent_id(ticket: dict) -> str:
    """agent_id du run 'work' (codeur) du ticket, ou "" si absent.
    Les runs sont insérés en tête (add_run insert(0)) : le premier 'work' est le plus récent."""
    work = next((r for r in ticket.get("runs", []) if r.get("kind") == "work"), None)
    return work.get("agent_id", "") if work else ""


def _build_run_to_work_map() -> dict[str, str]:
    """Map agent_id (de n'importe quel run) -> agent_id du run 'work' du MÊME ticket.

    Balaie TOUS les tickets de TOUS les projets, archivés compris (un validateur hérité
    peut appartenir à un ticket déjà archivé) — c'est exactement ce que rend `all_tickets()`.

    Balayait avant `TICKETS_DIR.glob("*.json")` : depuis la migration SQLite ces fichiers
    sont renommés `.json.migrated` et il n'en reste AUCUN, donc la map était TOUJOURS vide
    et la migration ne reparentait plus jamais personne, en silence."""
    mapping: dict[str, str] = {}
    for _slug, ticket in tickets.all_tickets():
        work_id = _work_agent_id(ticket)
        if not work_id:
            continue
        for run in ticket.get("runs", []):
            run_agent = run.get("agent_id")
            if run_agent:
                mapping[run_agent] = work_id
    return mapping


def migrate_orphan_validators() -> int:
    """Réécrit le parent des sous-agents hérités (validateur/auto-merge) orphelins.

    Pour chaque agent dont parent ∈ _LEGACY_PARENTS, retrouve le codeur (run 'work') du
    même ticket et réécrit parent = work.agent_id. Idempotent : un agent déjà migré ne
    porte plus un parent littéral, il est donc ignoré au run suivant. Renvoie le nombre
    d'agents effectivement reparentés."""
    run_to_work = _build_run_to_work_map()
    migrated = 0
    for agent in runner.list_agents():
        if agent.parent not in _LEGACY_PARENTS:
            continue
        work_id = run_to_work.get(agent.agent_id)
        if not work_id or work_id == agent.agent_id:
            # Pas de codeur retrouvé (ticket disparu) OU l'agent EST le codeur : on ne
            # touche pas (le fallback front s'en chargera par branche/worktree).
            logger.info(
                "migrate_orphan_validators: %s (parent=%s) sans codeur résolu, laissé au fallback front",
                agent.agent_id, agent.parent,
            )
            continue
        old_parent = agent.parent
        agent.parent = work_id
        runner._save(agent)
        migrated += 1
        logger.info(
            "migrate_orphan_validators: %s reparenté %s -> %s (codeur du même ticket)",
            agent.agent_id, old_parent, work_id,
        )
    if migrated:
        logger.info("migrate_orphan_validators: %d sous-agent(s) hérité(s) reparenté(s)", migrated)
    return migrated


# Marqueur d'idempotence de `migrate_inflight_tickets` : posé sur le ticket, jamais retiré.
_CHAIN_REMOVED_FLAG = "chain_removed_migrated"

_CHAIN_REMOVED_COMMENT = (
    "ℹ️ La chaîne automatique travail→validation→merge a été RETIRÉE : ce ticket "
    "n'avancera plus tout seul. Rien n'a été supprimé ni mergé — le worktree et la "
    "branche sont intacts. Le ticket repasse « à relire » : relance l'agent, lance un "
    "validateur, ou intègre-le quand tu le décides (bouton Intégrer)."
)

# Drapeaux posés par la chaîne retirée : sans eux le ticket resterait étiqueté d'un
# échec produit par un automatisme qui n'existe plus.
_STALE_CHAIN_FLAGS = ("gate_failed_cap", "launching")

_ACTIVE_RUN_STATES = ("running", "starting", "awaiting_input", "awaiting_plan_validation")


def _is_inflight(ticket: dict) -> bool:
    """Ticket EN VOL : il a du travail livré, aucune issue terminale, et plus aucun run
    actif — donc plus aucune transition ne le fera bouger depuis le retrait de la chaîne."""
    if ticket.get(_CHAIN_REMOVED_FLAG) or ticket.get("done") or ticket.get("crashed"):
        return False
    if ticket.get("reaped"):
        return False
    meta = ticket.get("worktree")
    if isinstance(meta, dict) and meta.get("state") in ("integrated", "cleaned", "needs_attention"):
        return False
    runs = [r for r in ticket.get("runs") or [] if isinstance(r, dict)]
    if not runs:
        return False  # jamais lancé : reste « à faire », rien à migrer
    return not any(r.get("state") in _ACTIVE_RUN_STATES for r in runs)


def migrate_inflight_tickets() -> int:
    """Bascule en « à relire » les tickets qui attendaient une étape désormais supprimée.

    Un ticket laissé en `work_done` / `validating` par l'ancienne chaîne n'a plus aucune
    transition qui matche : il resterait affiché « en cours » pour toujours. On purge ses
    drapeaux d'échec devenus sans objet, on pose UN commentaire qui explique pourquoi, et
    on marque le ticket migré. IDEMPOTENTE (le marqueur bloque le second passage), NON
    DESTRUCTIVE (rien n'est supprimé, rien n'est mergé) et LOGGÉE. Renvoie le nombre de
    tickets migrés."""
    migrated = 0
    for project in projects.list_projects():
        slug = project["slug"]
        # refresh=True attache l'état LIVE de chaque run : c'est ce qui distingue un ticket
        # réellement en vol d'un agent encore en train de travailler (qu'on ne touche pas).
        for ticket in tickets.list_tickets(slug, refresh=True):
            if not _is_inflight(ticket):
                continue
            for flag in _STALE_CHAIN_FLAGS:
                ticket.pop(flag, None)
            ticket[_CHAIN_REMOVED_FLAG] = True
            tickets.update_ticket(slug, ticket)
            tickets.add_comment(slug, ticket, _CHAIN_REMOVED_COMMENT, True)
            migrated += 1
            logger.info("migrate_inflight_tickets: %s/%s repassé « à relire »", slug, ticket["id"])
    if migrated:
        logger.info("migrate_inflight_tickets: %d ticket(s) en vol repassé(s) « à relire »", migrated)
    return migrated
