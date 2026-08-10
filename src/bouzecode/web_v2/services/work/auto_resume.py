"""Reprise AUTOMATIQUE des SOUS-AGENTS crashés, jouée au boot du serveur.

Décision produit (CHANTIER 1) : le bandeau /api/interrupted ne liste QUE les
MÉTA-AGENTS (runs 'work' dont le ticket est une demande utilisateur — parent vide
ou 'dispatcher:*'), car eux seuls se relancent MANUELLEMENT. Les SOUS-AGENTS de la
machinerie (runs 'validate', 'merge', et 'work' dispatchés par un manager, i.e.
parent = agent_id d'un autre agent) sont au contraire REPRIS AUTOMATIQUEMENT ici,
puis n'apparaissent PAS dans le bandeau — sauf si leur reprise a échoué.

Garde-fous (impératifs) :
  - reprendre SEULEMENT si le ticket est encore OUVERT (pas done/archived) ;
  - UNE seule tentative par boot, via un FLAG PERSISTANT sur le run
    (`run['auto_resumed']`) → un double boot ne retente pas ;
  - reprises SÉQUENTIELLES (pas de parallélisme) ;
  - JAMAIS un run SUPPLANTÉ par une tentative postérieure du même ticket (cf.
    `_superseded_reason`) : le ticket a été relancé, son travail est fait ailleurs ;
  - COMMENTAIRE DE TRACE écrit sur le ticket à chaque reprise ;
  - si la reprise échoue → `run['auto_resume_error']` posé (raison), ce qui fait
    RÉAPPARAÎTRE le run dans le bandeau (cf. interrupted_report._scan_tickets) ;
  - JAMAIS de reprise auto d'un méta-agent.

Best-effort : toute erreur est isolée par run et n'empêche jamais le boot.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from bouzecode.web_v2.services.sessions import recovery
from bouzecode.web_v2.services.work import liveness, reaper, tickets, wake

logger = logging.getLogger(__name__)

DEFAULT_RESUME_PROMPT = recovery.DEFAULT_RELAUNCH_PROMPT


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_subagent_run(ticket: dict, run: dict) -> bool:
    """Un run est un SOUS-AGENT (repris auto) ssi :
    - kind 'validate*' ou 'merge' (toujours machinerie), OU
    - kind 'work' ET ticket dispatché par un manager (parent = agent_id).
    Un run 'work' dont le ticket est une demande utilisateur (parent vide ou
    'dispatcher:*') est un MÉTA-AGENT → jamais repris auto."""
    kind = str(run.get("kind", ""))
    if kind.startswith("validate") or kind == "merge":
        return True
    if kind == "work":
        return wake.is_manager_parent(str(ticket.get("parent", "") or ""))
    return False


def _superseded_reason(ticket: dict, run: dict) -> str | None:
    """Raison de refus si le run crashé est SUPPLANTÉ par un run POSTÉRIEUR du même ticket,
    None s'il est bien la dernière tentative en date.

    ORDRE DES RUNS : `tickets.add_run` insère chaque nouveau run EN TÊTE (`insert(0)`) —
    l'index 0 est le PLUS RÉCENT, et les runs qui PRÉCÈDENT un run donné lui sont
    POSTÉRIEURS. On se fie à cet ordre et PAS à `started_at`, absent des runs anciens. On
    repère le candidat par IDENTITÉ (`is`) et non par égalité : le store réel contient des
    tickets où le MÊME run figure plusieurs fois (agent_id répété), donc `list.index()`
    renverrait la première copie et fausserait la position.

    Un ticket relancé (`POST …/launch`) porte un run plus récent qui a fait le travail :
    reprendre l'ancien ferait naître un SECOND agent dans le worktree d'un ticket DÉJÀ
    LIVRÉ, sur une mission déjà accomplie."""
    runs = [r for r in (ticket.get("runs") or []) if isinstance(r, dict)]
    position = next((i for i, candidate in enumerate(runs) if candidate is run), None)
    if position is None:
        return None
    for later in runs[:position]:  # tout ce qui précède = postérieur dans le temps
        later_id = str(later.get("agent_id", "") or "")
        if not later_id:
            continue
        etat = liveness.classify_agent_run(ticket, later)
        if etat in ("running", "delivered"):
            return (f"run supplanté par un run postérieur du même ticket "
                    f"('{later.get('kind')}' agent {later_id}, {etat}) — le ticket a été "
                    f"relancé depuis, sa mission est déjà reprise ailleurs")
        # Un run postérieur lui-même crashé est une tentative PLUS RÉCENTE : c'est LUI qu'on
        # reprend (il passe avant dans la boucle), jamais l'antérieur — deux agents relancés
        # dans le même worktree se piétineraient. On ne teste PAS son `auto_resumed` : il
        # vient d'être stampé, s'en servir de condition désarmait le garde-fou.
        if etat == "crashed" and _is_subagent_run(ticket, later):
            return (f"run supplanté par un run postérieur du même ticket "
                    f"('{later.get('kind')}' agent {later_id}), lui-même la tentative "
                    f"la plus récente")
    return None


def resume_subagents(resume_fn=None) -> list[dict]:
    """Parcourt les tickets ouverts et reprend SÉQUENTIELLEMENT chaque run
    sous-agent crashé jamais encore tenté. Retourne la liste des tentatives
    {slug, ticket, agent_id, kind, ok, error} (pour log/tests).

    `resume_fn(agent_id, prompt) -> new_agent_id | None` est injectable pour les
    tests (défaut : recovery.relaunch, qui reprend la session via resume_agent)."""
    if resume_fn is None:
        resume_fn = recovery.relaunch
    attempts: list[dict] = []
    # `tickets.all_tickets()` lit le store SQLite (UNE requête, tous projets). L'ancienne
    # version itérait `TICKETS_DIR.glob("*.json")` : depuis la migration SQLite il ne reste
    # AUCUN de ces fichiers, donc la reprise auto ne reprenait PLUS RIEN, en silence.
    for slug, ticket in tickets.all_tickets():
        if ticket.get("done") or ticket.get("archived"):
            continue
        # SÉQUENTIEL, run après run : une reprise lance un process, on ne les parallélise pas.
        for run in [r for r in (ticket.get("runs") or []) if isinstance(r, dict)]:
            attempt = _maybe_resume_run(slug, ticket, run, resume_fn)
            if attempt is not None:
                attempts.append(attempt)
    return attempts


def _stamp_run(slug: str, ticket: dict, agent_id: str, fields: dict,
               comment_text: str = "") -> None:
    """Pose `fields` sur le run de `agent_id` (+ un commentaire de trace optionnel), via
    `_mutate` : read-modify-write ATOMIQUE de la SEULE ligne du ticket, sur la version
    FRAÎCHE relue en base.

    Pourquoi pas `update_ticket(slug, ticket)` comme avant : cet objet `ticket` vient d'un
    instantané chargé au début de la passe de boot, et une reprise réussie fait AUSSITÔT
    écrire l'agent relancé (add_run, comments…). Réécrire l'instantané entier écrasait ces
    mutations concurrentes sans erreur ni trace — le lost-update silencieux du 2026-07-27.
    On mute donc aussi l'objet en mémoire, pour que la suite de la passe le voie à jour."""
    def _apply(fresh: dict) -> None:
        for fresh_run in fresh.get("runs") or []:
            if isinstance(fresh_run, dict) and fresh_run.get("agent_id") == agent_id:
                fresh_run.update(fields)
        if comment_text:
            fresh.setdefault("comments", []).append(
                {"at": _now(), "text": comment_text, "sent": False})

    for run in ticket.get("runs") or []:  # miroir sur l'objet appelant
        if isinstance(run, dict) and run.get("agent_id") == agent_id:
            run.update(fields)
    if comment_text:
        ticket.setdefault("comments", []).append(
            {"at": _now(), "text": comment_text, "sent": False})
    try:
        tickets._mutate(slug, ticket["id"], _apply)
    except Exception:  # noqa: BLE001 — persistance best-effort, jamais fatale au boot
        logger.exception("persistance de l'auto-resume de %s a échoué", agent_id)


def _maybe_resume_run(slug: str, ticket: dict, run: dict, resume_fn) -> dict | None:
    """Tente de reprendre UN run s'il est un sous-agent crashé non déjà tenté.
    Mute `ticket`/`run` en mémoire ET persiste ligne par ligne via `_stamp_run`.
    Retourne le résumé de tentative ou None (skip)."""
    agent_id = str(run.get("agent_id", "") or "")
    if not agent_id:
        return None
    if run.get("auto_resumed"):
        return None  # flag persistant : déjà tenté à un boot précédent
    if not _is_subagent_run(ticket, run):
        return None  # méta-agent → jamais de reprise auto
    if liveness.classify_agent_run(ticket, run) != "crashed":
        return None  # vivant ou proprement clôturé → rien à reprendre

    kind = str(run.get("kind", ""))
    # Deux refus DÉFINITIFS, tracés de la même façon : worktree nettoyé (mergé/reapé), et run
    # supplanté par une tentative postérieure. `is_resume_blocked` est pur, donc testé d'abord
    # (l'autre classifie les runs postérieurs, ce qui lit le disque).
    blocked = reaper.is_resume_blocked(ticket) or _superseded_reason(ticket, run)
    if blocked:
        # Ticket mergé/reapé : son worktree a été nettoyé. Le relancer ferait
        # renaître l'agent dans un dossier fantôme (le bug 17d4122a). On pose le
        # flag persistant (jamais retenté), on trace la raison, on N'APPELLE PAS
        # resume_fn, et on renvoie un attempt en échec avec le message actionnable.
        _stamp_run(
            slug, ticket, agent_id,
            {"auto_resumed": _now(), "auto_resume_error": blocked},
            f"[auto-resume] reprise du sous-agent '{kind}' (agent {agent_id}) "
            f"REFUSÉE : {blocked}.",
        )
        return {"slug": slug, "ticket": ticket.get("id", ""), "agent_id": agent_id,
                "kind": kind, "ok": False, "error": blocked}

    # Le flag persistant est posé AVANT d'appeler resume_fn : si le serveur meurt pendant la
    # reprise, le boot suivant voit `auto_resumed` et ne retente PAS. L'inverse (stamper après)
    # transformait un crash au démarrage en boucle de relance à chaque boot.
    _stamp_run(
        slug, ticket, agent_id, {"auto_resumed": _now()},
        f"[auto-resume] reprise automatique du sous-agent '{kind}' "
        f"(agent {agent_id}) interrompu au dernier arrêt serveur.",
    )
    error = None
    try:
        new_id = resume_fn(agent_id, DEFAULT_RESUME_PROMPT)
        if not new_id:
            error = "resume_agent a renvoyé None (agent introuvable ou reprise refusée)"
    except Exception as exc:  # noqa: BLE001 — best-effort, on trace la raison
        error = f"{type(exc).__name__}: {exc}"
        logger.exception("auto-resume du sous-agent %s a échoué", agent_id)
    if error:
        # Pose `auto_resume_error` : c'est ce champ qui fait RÉAPPARAÎTRE le run dans le
        # bandeau des interrompus, avec sa raison (cf. interrupted_report._scan_tickets).
        _stamp_run(slug, ticket, agent_id, {"auto_resume_error": error})
    return {"slug": slug, "ticket": ticket.get("id", ""), "agent_id": agent_id,
            "kind": kind, "ok": error is None, "error": error}
