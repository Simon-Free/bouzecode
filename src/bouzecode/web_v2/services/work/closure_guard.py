# [desc] Garde-fou de CLÔTURE d'un manager : refuse « terminé » tant qu'un enfant n'a rien livré. [/desc]
"""Un manager ne peut pas être enregistré TERMINÉ tant qu'un de ses enfants a planté sans
rien livrer.

CAS RÉEL OBSERVÉ EN PRODUCTION : cinq enfants dispatchés, l'un d'eux — le cœur
fonctionnel de la demande utilisateur — est mort avec
returncode=-1, session de 102 octets, ZÉRO bloc produit, ZÉRO fichier écrit. Le manager a
néanmoins rendu « VERDICT: OK » et `wake._finalize_noncoding_parent` l'a stampé `done=True`.
Rien ne l'a bloqué parce que l'état des enfants n'est consulté QUE via `wake.ticket_terminal`,
où `crashed` EST une issue terminale VALIDE : « tous les enfants sont terminaux » était donc
VRAI, et la seule barrière de qualité restante était le verdict AUTO-DÉCLARÉ du manager
(`verdict == "KO"`). L'utilisateur s'est vu annoncer une livraison complète.

PREUVE DE LIVRAISON — la MÊME que `workflow._is_crash` : un run porte `completed` (posé par
le hook `/completed`, ou reconstruit par `wake._reconcile_graceful_close` quand le callback a
été perdu) ou un `verdict`. C'est exactement ce qui séparait, dans le cas réel, les quatre
enfants livrés du cinquième.

COÛT : les prédicats sont PURS et sans AUCUNE I/O — ce garde-fou est évalué à chaque tick du
watchdog, il ne lit que les dicts d'enfants DÉJÀ chargés par `wake._children_by_parent()`. Il
n'écrit dans le store que lorsque l'ensemble des enfants bloquants CHANGE (une écriture, pas
une par tick).

TOLÉRANCE (cohérente avec `reaper.is_resume_blocked` et les close_reasons gracieux de
`wake`) : un enfant archivé, acquitté à la main (`done`), ou mergé/fauché (worktree nettoyé →
la suite vit dans un ticket de suivi) ne gèle JAMAIS son parent. Un enfant RELANCÉ cesse de
bloquer dès son premier run (`add_run` retire `crashed`, puis `/completed` pose la preuve).

PORTE DE SORTIE HUMAINE : `POST /api/tickets/<slug>/<id>/done` stampe `CLOSURE_FORCED_KEY` ;
`refuse_closure` s'y range sans discuter."""
from __future__ import annotations

from . import reaper
from . import tickets as tickets_svc

# Persisté sur le ticket PARENT : les ids d'enfants qui interdisent sa clôture, joints par
# ';'. Lu par `_status.derive_status` (statut « clôture bloquée ») — c'est ce qui rend le
# blocage VISIBLE au lieu d'être un refus silencieux.
CLOSURE_BLOCKED_KEY = "closure_blocked"
# Persisté sur le ticket PARENT par la route `/done` : l'humain a clos EN CONNAISSANCE DE
# CAUSE. Le garde-fou ne repose plus jamais le blocage sur ce ticket.
CLOSURE_FORCED_KEY = "closure_forced"

_CRASHED_REASON = "planté sans aucune livraison (aucun run clos proprement, aucun verdict)"
_LAUNCH_FAILED_REASON = "lancement échoué : aucun agent n'a démarré, la tâche n'a pas commencé"
_SILENT_REASON = "aucune livraison prouvée (aucun run clos proprement, aucun verdict)"


def child_delivered_something(child: dict) -> bool:
    """L'enfant a-t-il une PREUVE de livraison ? (pur, zéro I/O)

    Preuve = un run porte `completed` (clôture gracieuse traitée par `/completed`, ou
    reconstruite par le reconciler) ou un `verdict`. Volontairement la même preuve que
    `workflow._is_crash` : deux définitions de « ce run a fini proprement » divergeraient."""
    return any(run.get("completed") or run.get("verdict")
               for run in child.get("runs") or [] if isinstance(run, dict))


def child_launched(child: dict) -> bool:
    """Un enfant sans aucun run n'a jamais démarré : il ne peut rien avoir livré, et il est
    déjà écarté du critère de réveil (`wake.has_launched`). On ne bloque pas sur lui — un
    enfant en cours de lancement est traité en amont par `wake.child_pending_launch`.

    EXCEPTION : un enfant dont le PROVISIONNEMENT a échoué (`launch_failed`) compte, lui, comme
    lancé. Il est désormais TERMINAL pour `wake.ticket_terminal` (sinon son parent attendait un
    verdict qui ne viendrait jamais) : sans cette exception, `_finalize_noncoding_parent`
    stamperait le manager « terminé » par-dessus une tâche qui n'a même pas commencé — le
    mensonge exact que ce garde-fou existe pour empêcher."""
    runs = child.get("runs")
    if isinstance(runs, list) and len(runs) > 0:
        return True
    return bool(child.get("launch_failed"))


def child_excused(child: dict) -> bool:
    """L'enfant est-il DISPENSÉ de bloquer son parent ? (pur)

    Trois dispenses, toutes des DÉCISIONS déjà prises et tracées ailleurs :
    - `archived` : retrait volontaire du board par l'utilisateur (travail abandonné) ;
    - `done` : acquitté à la main, l'humain a déjà statué sur cet enfant ;
    - `reaper.is_resume_blocked` non None (mergé/fauché) : son worktree est nettoyé, il n'est
      PLUS relançable — le geler éternellement condamnerait le parent sans recours possible ;
      la suite vit dans un ticket de suivi.
    Un enfant simplement RELANCÉ n'a pas besoin de dispense : son nouveau run retire `crashed`
    et son `/completed` pose la preuve de livraison."""
    if child.get("archived") or child.get("done"):
        return True
    return reaper.is_resume_blocked(child) is not None


def blocking_children(child_tickets: list[dict]) -> list[tuple[str, str]]:
    """Les enfants qui INTERDISENT la clôture du parent : [(id, raison)]. PUR, zéro I/O.

    Un enfant bloque quand il a été lancé, n'est pas dispensé, et n'a AUCUNE preuve de
    livraison. Le drapeau `crashed` ne conditionne pas le blocage, il en précise la raison :
    un enfant mort dont le watchdog n'a pas encore posé `crashed` (debounce `_CRASH_DEAD_TICKS`)
    est déjà `ticket_terminal` pour `wake`, donc il finalisait le parent tout aussi
    silencieusement. Un enfant `crashed` qui a DÉJÀ livré (run completed/verdict d'une passe
    précédente) ne bloque PAS : son travail existe et son crash est visible sur le board."""
    blocking: list[tuple[str, str]] = []
    for child in child_tickets:
        if not isinstance(child, dict) or not child.get("id"):
            continue
        if not child_launched(child) or child_excused(child):
            continue
        if child_delivered_something(child):
            continue
        if child.get("launch_failed"):
            reason = _LAUNCH_FAILED_REASON
        else:
            reason = _CRASHED_REASON if child.get("crashed") else _SILENT_REASON
        blocking.append((child["id"], reason))
    return blocking


def block_signature(blocking: list[tuple[str, str]]) -> str:
    """Signature stable de la situation de blocage (ids triés). Même rôle que
    `wake.children_signature` : un blocage identique ne se re-trace pas, un blocage qui
    CHANGE (un enfant relancé, un autre tombé) se re-trace une fois."""
    return ";".join(sorted(child_id for child_id, _ in blocking))


def block_comment(slug: str, ticket_id: str, blocking: list[tuple[str, str]]) -> str:
    """Le commentaire de trace posé sur le ticket manager : nomme CHAQUE enfant fautif, la
    raison, et les deux sorties (relancer/archiver l'enfant, ou forcer la clôture)."""
    lines = ["⛔ Clôture BLOQUÉE : ce manager ne peut pas être enregistré « terminé » tant "
             "que ces enfants n'ont rien livré :"]
    lines += [f"- enfant {child_id} : {reason}" for child_id, reason in blocking]
    lines += [
        "Relance l'enfant (bouton Relancer sur son ticket) s'il reste du travail, ou "
        "archive-le si son travail est abandonné ou repris par un autre ticket.",
        f"Pour clore malgré tout EN CONNAISSANCE DE CAUSE : POST "
        f"/api/tickets/{slug}/{ticket_id}/done (bouton Terminé) — la clôture forcée sera tracée.",
    ]
    return "\n".join(lines)


def _record_block(slug: str, ticket: dict, blocking: list[tuple[str, str]]) -> bool:
    """Trace le blocage sur le ticket parent — flag + commentaire — en UNE mutation atomique,
    et SEULEMENT quand la situation a changé (sinon le watchdog écrirait toutes les 8 s).
    Renvoie True si une trace a été posée."""
    signature = block_signature(blocking)
    if ticket.get(CLOSURE_BLOCKED_KEY) == signature:
        return False
    comment = {"at": tickets_svc._now(),
               "text": block_comment(slug, ticket["id"], blocking), "sent": False}

    def _apply(fresh: dict) -> None:
        fresh[CLOSURE_BLOCKED_KEY] = signature
        fresh.setdefault("comments", []).append(comment)

    tickets_svc._mutate(slug, ticket["id"], _apply)  # read-modify-write d'UNE ligne
    ticket[CLOSURE_BLOCKED_KEY] = signature  # miroir sur l'objet appelant
    ticket.setdefault("comments", []).append(comment)
    return True


def _clear_block(slug: str, ticket: dict) -> bool:
    """Lève la trace de blocage (tous les enfants ont livré depuis). Sans ça le statut
    « clôture bloquée » survivrait à la résurrection de l'enfant, comme le faisait le
    drapeau `crashed` avant `wake.crash_is_contradicted`."""
    if not ticket.get(CLOSURE_BLOCKED_KEY):
        return False
    tickets_svc._mutate(slug, ticket["id"],
                        lambda fresh: fresh.pop(CLOSURE_BLOCKED_KEY, None))
    ticket.pop(CLOSURE_BLOCKED_KEY, None)
    return True


def refuse_closure(slug: str, parent: dict, child_tickets: list[dict]) -> list[tuple[str, str]]:
    """LE point d'entrée du garde-fou : renvoie les enfants bloquants ([] = clôture permise),
    et maintient la trace visible sur le ticket parent (posée une fois, levée dès que le
    blocage disparaît). Une clôture FORCÉE par l'humain (`CLOSURE_FORCED_KEY`) court-circuite
    tout : c'est sa décision, prise avec la liste des enfants fautifs sous les yeux."""
    if parent.get(CLOSURE_FORCED_KEY):
        return []
    blocking = blocking_children(child_tickets)
    if blocking:
        _record_block(slug, parent, blocking)
    else:
        _clear_block(slug, parent)
    return blocking


def force_closure(slug: str, ticket: dict) -> str:
    """Porte de sortie EXPLICITE de l'humain, appelée par `POST .../done` : convertit le
    blocage en clôture FORCÉE et TRACÉE. Renvoie la signature forcée ("" si rien n'était
    bloqué). Le flag remplace le blocage plutôt que de cohabiter avec lui : sinon
    `derive_status` continuerait d'afficher « clôture bloquée » sur un ticket que l'humain
    vient d'acter, et le statut mentirait dans l'autre sens."""
    signature = ticket.get(CLOSURE_BLOCKED_KEY) or ""
    if not signature:
        return ""
    comment = {"at": tickets_svc._now(), "sent": False, "text":
               "⚠️ Clôture FORCÉE à la main alors que ces enfants n'avaient rien livré : "
               f"{signature.replace(';', ', ')}. Décision explicite de l'utilisateur — le "
               "garde-fou de clôture ne repose plus le blocage sur ce ticket."}

    def _apply(fresh: dict) -> None:
        fresh.pop(CLOSURE_BLOCKED_KEY, None)
        fresh[CLOSURE_FORCED_KEY] = signature
        fresh.setdefault("comments", []).append(comment)

    tickets_svc._mutate(slug, ticket["id"], _apply)
    ticket.pop(CLOSURE_BLOCKED_KEY, None)
    ticket[CLOSURE_FORCED_KEY] = signature
    ticket.setdefault("comments", []).append(comment)
    return signature
