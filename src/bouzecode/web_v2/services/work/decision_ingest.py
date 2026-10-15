"""Alimente la table `decisions` depuis l'état réel du parc, à chaque tick du watchdog.

Le Bureau ne doit pas dire « à relire » : il doit dire l'ACTE QUI RESTE. Une carte de décision
n'est donc jamais devinée par un LLM, elle est DÉRIVÉE de deux sources factuelles :

- une question qu'un agent a réellement posée (`awaiting.agents_awaiting_answer()`), qui survit
  ici à la mort de son agent — c'est tout l'objet de la table (sa date arrive en UTC avec
  fuseau, elle est normalisée par `_asked_at_iso` comme toutes les autres) ;
- une situation mesurée sur le dépôt : des commits livrés que personne n'a intégrés
  (`unmerged.scan_ticket`, seul endroit git du lot).

Pourquoi ici et pas dans `GET /api/board` : ingérer depuis une lecture prendrait un write-lock
SQLite sur le chemin le plus chaud du produit (budget 300 ms p95), et ferait dépendre l'affichage
d'appels git. Le board LIT `decisions`, il ne l'écrit jamais. Pourquoi pas dans
`reconcile_tasks_with_tickets()` non plus : cette fonction promet « aucun appel git » et le tient.
L'ingest s'accroche À CÔTÉ d'elle, APRÈS elle (les tâches doivent exister pour être référencées).
"""

from __future__ import annotations

import logging

from bouzecode.web_v2.services.horodatage import en_iso, maintenant_iso

from . import awaiting, decisions, tasks as tasks_service, unmerged
from .tickets import all_tickets, poser

_log = logging.getLogger(__name__)

SITUATION_UNMERGED = "livraison_a_relire"

# Les quatre actes possibles devant une livraison non intégrée (§6.3). Ce sont des ACTES,
# pas des états : chacun se traduit par un appel existant (integration.integrate_ticket,
# messaging.send_to_ticket_agent, branch_rescue.drop_branch).
OPTIONS_UNMERGED = [
    {"key": "integrer", "label": "Intégrer la branche"},
    {"key": "corriger", "label": "Renvoyer l'agent corriger"},
    {"key": "valider", "label": "Relire d'abord le diff"},
    {"key": "abandonner", "label": "Abandonner la branche"},
]


def _now() -> str:
    """L'instant courant dans la FORME UNIQUE des `asked_at` (voir `_asked_at_iso`)."""
    return maintenant_iso()


def _asked_at_iso(valeur: object) -> str:
    """Ramène une date d'origine quelconque à la forme unique des `asked_at`.

    FORME UNIQUE (contrat de la colonne `decisions.asked_at`, celle de tout le store) : ISO 8601
    à la seconde, UTC, décalage TOUJOURS explicite — `2026-07-28T15:26:01+00:00`.

    Les cartes naissaient avec deux formats selon leur origine (locale naïve pour une livraison,
    UTC pour une question d'agent), et le board finissait par soustraire une naïve d'une aware —
    500 sur `/api/board`. On normalise à l'écriture ; la lecture reste tolérante
    (`horodatage.lire_instant`) parce que la base porte encore des dates locales, naïves ou à
    décalage `+02:00`. Une date naïve est réputée LOCALE : la « supposer UTC » décalerait de
    7 200 s et fabriquerait des attentes fantômes de deux heures.
    """
    if not valeur:
        return _now()
    if not isinstance(valeur, str):
        _log.warning("decision_ingest: asked_at n'est pas une date (%r), horodaté à maintenant", valeur)
        return _now()
    normalisee = en_iso(valeur)
    if not normalisee:
        _log.warning("decision_ingest: asked_at illisible (%r), horodaté à maintenant", valeur)
        return _now()
    return normalisee


def _task_index() -> dict[tuple[str, str], str]:
    """`(slug, ticket_id) -> task_id`, en UNE lecture. Un ticket sans tâche donne "" : la carte
    existe quand même, elle sera rattachée au tick suivant plutôt que perdue."""
    index: dict[tuple[str, str], str] = {}
    for link in tasks_service.all_links():
        slug = str(link.get("slug") or "")
        ticket_id = str(link.get("ticket_id") or "")
        task_id = str(link.get("task_id") or "")
        index[(slug, ticket_id)] = task_id
        # Clé de SECOURS, par ticket seul : la question d'un agent arrive avec le slug déduit par
        # `awaiting` (liste des projets), qui peut être VIDE quand le projet n'y figure pas. Sans
        # ce repli, la carte naissait avec `task_id=""` — donc invisible pour `count_open_by_task`
        # (SQL `task_id != ''`), donc une question en attente depuis 21 jours (agent 44aa28606276,
        # ticket 5c75d2d9, tâche 0747eea8) n'empêchait PAS la clôture automatique de sa tâche.
        # `setdefault` : le premier lien gagne, et une clé exacte n'est jamais écrasée.
        index.setdefault(("", ticket_id), task_id)
    return index


def _task_of(index: dict[tuple[str, str], str], slug: str, ticket_id: str) -> str:
    """Tâche d'un ticket, le slug étant peu fiable côté agents. Le repli par ticket seul ne
    s'active QUE si le couple exact a échoué : un `ticket_id` est un hex de 8 à 12 caractères,
    la collision inter-projets est négligeable, et rattacher au mauvais projet resterait très
    supérieur à ne rattacher à RIEN (une décision orpheline ne bloque aucune clôture)."""
    return index.get((slug, ticket_id)) or index.get(("", ticket_id), "")


def _recommended(ticket: dict) -> str:
    """Recommandation par RÈGLE, jamais par un modèle : un ticket que son agent a mené à son
    terme se recommande à l'intégration ; un ticket interrompu se recommande à la correction."""
    return "integrer" if ticket.get("state") in ("delivered", "closed") else "corriger"


def _unmerged_card(slug: str, ticket: dict, task_id: str) -> str:
    """Ouvre / rafraîchit / classe la carte « livraison non intégrée » d'UN ticket.

    Rend "opened" | "moot" | "none". `bucket=""` : la clé de dédup ne porte QUE la situation et
    le ticket, sinon un `asked_at` qui bouge à chaque tick créerait une carte par minute.
    """
    from ._status import remaining_of
    ticket_id = str(ticket.get("id") or "")
    count = remaining_of(ticket)["unmerged_commits"]
    if count <= 0:
        classees = decisions.make_moot_where(
            SITUATION_UNMERGED, ticket_id, "plus aucun travail non intégré (au plus un résidu "
            "de fichiers de méta)")
        return "moot" if classees else "none"
    decisions.upsert(
        source="situation",
        situation=SITUATION_UNMERGED,
        question=_question_unmerged(ticket, count),
        asked_at=_now(),
        task_id=task_id,
        project_slug=slug,
        ticket_id=ticket_id,
        agent_id=str(ticket.get("agent_id") or ""),
        context=str(ticket.get("title") or ""),
        options=OPTIONS_UNMERGED,
        allow_freetext=True,
        recommended=_recommended(ticket),
        urgency=1,
        bucket="",
    )
    return "opened"


def _question_unmerged(ticket: dict, count: int) -> str:
    """La carte NOMME le mécanisme : travail jamais intégré, ou résidu ajouté sur la branche
    APRÈS son intégration (l'agent a continué, ou une récolte tardive)."""
    meta = ticket.get("worktree") or {}
    branch, base = str(meta.get("branch") or ""), str(meta.get("base") or "")
    pluriel = "s" if count > 1 else ""
    fusion = str((ticket.get("integration") or {}).get("merged_at") or "") if isinstance(
        ticket.get("integration"), dict) else ""
    if fusion:
        return (f"Résidu post-intégration : {count} commit{pluriel} ajouté{pluriel} sur "
                f"`{branch}` APRÈS son intégration dans `{base}` ({fusion[:16]}). "
                "Qu'est-ce qu'on en fait ?")
    return (f"Travail jamais intégré : {count} commit{pluriel} livré{pluriel} sur `{branch}` "
            f"que personne n'a intégré{pluriel} dans `{base}`. Qu'est-ce qu'on en fait ?")


def _question_cards(index: dict[tuple[str, str], str]) -> int:
    """Une carte par question d'agent réellement posée, et UNE SEULE.

    `bucket=""` : la clé ne porte que (situation, ticket, agent). Le bucket par défaut —
    la MINUTE de `asked_at` — paraissait stable mais ne l'était pas : dès que la question
    n'est pas horodatée à la seconde près par la source, la minute rendue bouge d'un tick
    à l'autre et fabrique une carte de plus à chaque passage. Mesuré sur le board réel :
    30 décisions dont 3 questions présentes 2 fois (agents en attente depuis 21/25/27 j).
    Un agent n'attend qu'UNE réponse à la fois (`awaiting.agents_awaiting_answer` rend une
    seule ligne par agent), donc la clé sans bucket est la bonne identité."""
    ouvertes = 0
    for row in awaiting.agents_awaiting_answer():
        slug = str(row.get("project_slug") or "")
        ticket_id = str(row.get("ticket_id") or "")
        decisions.upsert(
            source="agent_question",
            situation="question_agent",
            question=str(row.get("question") or "Cet agent attend une réponse."),
            asked_at=_asked_at_iso(row.get("asked_at")),
            task_id=_task_of(index, slug, ticket_id),
            project_slug=slug,
            ticket_id=ticket_id,
            agent_id=str(row.get("agent_id") or ""),
            context=str(row.get("title") or ""),
            options=row.get("options") or [],
            allow_freetext=bool(row.get("allow_freetext", True)),
            recommended="",
            urgency=0,
            bucket="",
        )
        #  Les cartes écrites AVANT la stabilisation de la clé gardent leur ancienne
        #  clé : on les ferme ici, sinon le doublon reste au board pour toujours.
        agent_id = str(row.get("agent_id") or "")
        decisions.close_other_duplicates(
            situation="question_agent",
            ticket_id=ticket_id,
            agent_id=agent_id,
            keep_key=decisions.dedup_key("question_agent", ticket_id, agent_id,
                                         bucket=""),
            trace="doublon de la même question (une carte par minute avant correctif)",
        )
        ouvertes += 1
    return ouvertes


def _tickets_a_carte_ouverte() -> set[str]:
    """Les tickets qui portent encore une carte « livraison à relire » ouverte (une requête)."""
    return {str(row.get("ticket_id") or "") for row in decisions.open_decisions(limit=100000)
            if row.get("situation") == SITUATION_UNMERGED}


def _purger_si_sans_objet(ticket: dict) -> bool:
    """Classe la carte d'un ticket rangé dont le worktree ET la branche n'existent plus.

    Cas réel (essai du 2026-09-24) : trois cartes restaient ouvertes sur des tickets archivés,
    fauchés, branche supprimée — l'ingest sautait les archivés avant de regarder leurs cartes.
    Dépôt introuvable = objet invérifiable : on ne touche à rien (`disparition` rend "")."""
    from . import decisions_sans_objet
    trace = decisions_sans_objet.disparition(ticket)
    if not trace:
        return False
    motif = trace.replace("Archivée automatiquement : décision sans objet — ", "")
    return decisions.make_moot_where(SITUATION_UNMERGED, str(ticket.get("id") or ""),
                                     f"livraison sans objet : {motif}") > 0


def ingest() -> dict[str, int]:
    """Un tour d'ingestion. À rejouer en continu : tout y est idempotent (clé de dédup).

    Rend `{"scanned","skipped","unmerged","moot","questions"}` — `scanned` compte les tickets
    pour lesquels un `git rev-list` a réellement tourné (les autres sont mémoïsés sur leur tip).
    """
    index = _task_index()
    scanned = skipped = ouvertes = classees = 0

    cartes_ouvertes = _tickets_a_carte_ouverte()
    # Une passe : les refs de chaque dépôt ne sont lues qu'une fois (cf. unmerged.une_passe).
    with unmerged.une_passe():
        for slug, ticket in all_tickets():
            if ticket.get("archived"):
                #  Rangé : plus aucun git SAUF pour classer une carte restée ouverte dont la
                #  branche a disparu (sinon plus rien ne la classerait jamais).
                if str(ticket.get("id") or "") in cartes_ouvertes and _purger_si_sans_objet(ticket):
                    classees += 1
                continue
            avant = (unmerged.marker_de(ticket), "unmerged_tip" in ticket)
            if unmerged.scan_ticket(ticket) == "scanned":
                scanned += 1
            else:
                skipped += 1
            # Persisté SEULEMENT si le repère a bougé : le reconcile du tick suivant relira ce
            # constat pour clore la tâche sans refaire de git, et on n'écrit pas 220 tickets par
            # tick. Un ticket d'avant L3 perd ici ses anciens `unmerged_*` (remplacés).
            if (unmerged.marker_de(ticket), "unmerged_tip" in ticket) != avant:
                poser(slug, ticket, delivery=ticket.get("delivery"), unmerged_commits=None,
                      unmerged_tip=None)
            verdict = _unmerged_card(slug, ticket, index.get((slug, str(ticket.get("id") or "")), ""))
            if verdict == "opened":
                ouvertes += 1
            elif verdict == "moot":
                classees += 1

    questions = _question_cards(index)
    return {"scanned": scanned, "skipped": skipped, "unmerged": ouvertes,
            "moot": classees, "questions": questions}
