# [desc] Gestes GLOBAUX du tick du watchdog, hors réconciliation des tickets : pool chaud, vérifications différées des agents finis, rattrapage du Bureau. [/desc]
"""Extrait de `wake.py` (seuil ~200 lignes). Appelés par `wake.tick` à chaque cycle, hors de
la boucle par projet : ils ne dépendent pas du filtre `ticket_needs_watchdog`. Aucun n'est
déclenché par une lecture (GET) : le pool chaud n'est évincé que par ce tick et par
la création d'un ticket lancé (B1, R11)."""
from __future__ import annotations

import logging
import threading

_log = logging.getLogger(__name__)
_DRAINS_EN_COURS: set[str] = set()
_VERROU_DRAINS = threading.Lock()


def drainer_les_verifications_differees() -> list[str]:
    """Les agents finis sur une clôture DIFFÉRÉE (`<session>.deferred.json` à côté de leur
    session) voient leurs vérifications exécutées, chacun dans son fil : tout vert clôt, un échec
    relance l'agent pour corriger (`runner._maybe_drain_deferred`). Ce geste vivait dans
    `refresh_agent_status`, donc dans les LECTURES (spec B1) ; il ne vit plus qu'ici. Rend les
    agents dont le drain a démarré à ce tick (un drain déjà en cours n'est jamais doublé)."""
    from ...runtime.runner import agent_etat, agent_fiche
    demarres = []
    for chemin in sorted(agent_fiche.AGENTS_DIR.glob("*.session.json.deferred.json")):
        agent = agent_fiche.load_agent(chemin.name.split(".", 1)[0])
        if agent is None or agent_etat.refresh_agent_status(agent).returncode is None:
            continue  # inconnu, ou process encore là : son drain attendra sa fin
        with _VERROU_DRAINS:
            if agent.agent_id in _DRAINS_EN_COURS:
                continue
            _DRAINS_EN_COURS.add(agent.agent_id)
        threading.Thread(target=_drainer, args=(agent,), daemon=True,
                         name=f"differes-{agent.agent_id[:8]}").start()
        demarres.append(agent.agent_id)
    return demarres


def _drainer(agent) -> None:
    from ...runtime.runner import agent_reprise
    try:
        agent_reprise._maybe_drain_deferred(agent)
    except Exception:  # noqa: BLE001 — un drain cassé ne tue pas le watchdog ; il est journalisé
        _log.exception("vérifications différées de %s : échec du drain", agent.agent_id)
    finally:
        with _VERROU_DRAINS:
            _DRAINS_EN_COURS.discard(agent.agent_id)


def balayer_le_pool_chaud() -> None:
    """Balayage GLOBAL du warm-pool, à CHAQUE tick — hors de la boucle par projet.

    `fleet.sweep_warm_pool` est aussi appelé à la création d'un ticket lancé (moment causal : un
    dispatch ajoute un process). Il manque le cas « aucun dispatch pendant des heures » :
    sans ce tick, le pool ne serait jamais balayé. C'est justement quand plus rien ne
    tourne qu'il faut libérer les process idle — donc ce balayage ne doit PAS dépendre du
    filtre `ticket_needs_watchdog`, qui ne concerne QUE la réconciliation des tickets.

    Import LOCAL, obligatoire : `fleet` importe `liveness`, qui importe `wake` en tête de
    module — un import de `fleet` ici serait un cycle. Résilient : un pool qu'on n'a pas su
    balayer ne doit jamais empêcher le tick suivant de réconcilier les tickets."""
    from . import fleet
    try:
        fleet.sweep_warm_pool()
    except Exception:  # noqa: BLE001 — le ménage du pool ne tue jamais le watchdog
        _log.exception("wake.tick: balayage du warm-pool a échoué")


def rattraper_le_bureau() -> None:
    """Rattrapage GLOBAL des tâches du Bureau, à CHAQUE tick — hors de la boucle par projet.

    `migrate_tickets_into_tasks` n'était appelée qu'au boot (`create_app`) : un ticket créé
    ensuite ne devenait JAMAIS une tâche, et le board n'était que l'instantané du dernier
    démarrage. On se greffe ici plutôt que d'ouvrir un second poller (le watchdog tourne déjà
    toutes les 8 s) et plutôt que sur `GET /api/board`, qui doit rester une lecture pure : un
    GET qui écrit prendrait un write-lock sur le chemin le plus chaud du Bureau.

    Hors de la boucle par projet, DÉLIBÉRÉMENT : le rattrapage ne concerne pas la réconciliation
    des runs, il ne doit donc pas dépendre du filtre `ticket_needs_watchdog` — un projet dont
    tous les tickets ont fini leur comptabilité doit quand même voir ses tâches à jour.

    Import LOCAL et résilience, même motif que `balayer_le_pool_chaud` : un rattrapage qui échoue ne
    doit jamais empêcher le tick suivant de réconcilier les tickets."""
    from . import decision_ingest, task_migration
    try:
        task_migration.reconcile_tasks_with_tickets()
    except Exception:  # noqa: BLE001 — le board du Bureau ne tue jamais le watchdog
        _log.exception("wake.tick: rattrapage des tâches du Bureau a échoué")
    # APRÈS le reconcile : les tâches doivent exister avant qu'on leur attache des décisions.
    # Garde SÉPARÉE, délibérément : c'est le seul endroit du Bureau qui lance du git, et une
    # panne git (repo verrouillé, disque) ne doit pas priver le board de sa réconciliation —
    # ni l'inverse. Une garde partagée transformerait chaque panne en panne double.
    try:
        decision_ingest.ingest()
    except Exception:  # noqa: BLE001 — idem : l'ingestion ne tue jamais le watchdog
        _log.exception("wake.tick: ingestion des décisions du Bureau a échoué")
    from . import brouillons_integres
    try:
        brouillons_integres.balayer()
    except Exception:  # noqa: BLE001 — idem : un brouillon resté affiché ne tue pas le watchdog
        _log.exception("wake.tick: archivage des brouillons de fusion a échoué")
    from . import decisions_sans_objet
    try:
        decisions_sans_objet.balayer()
    except Exception:  # noqa: BLE001 — idem : une décision restée affichée ne tue pas le watchdog
        _log.exception("wake.tick: archivage des décisions sans objet a échoué")
    from . import orphelins
    try:
        orphelins.balayer()
    except Exception:  # noqa: BLE001 — idem : une tâche restée « Sans chantier » ne tue pas le watchdog
        _log.exception("wake.tick: rattachement des tâches orphelines a échoué")
