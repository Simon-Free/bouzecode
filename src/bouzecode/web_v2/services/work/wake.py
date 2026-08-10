# [desc] Réveil du manager parent quand tous ses enfants sont terminaux + WATCHDOG reconciler crash-aware (actif par défaut). [/desc]
"""Réveil des managers + filet de réconciliation.

La chaîne automatique travail→validation→merge a été RETIRÉE : plus rien n'avance un
ticket tout seul. Ce qui reste ici est l'OBSERVABILITÉ, indispensable justement parce
que le manager décide de tout : `process_wakes`/`build_wake_digest` (réveil du parent
quand TOUS ses enfants sont terminaux) et le WATCHDOG (`tick`/`start_poller`, ACTIF par
défaut, opt-out BOUZECODE_WAKE_POLLER=0) : reconciler crash-aware qui stampe la vivacité
(`_stamp_liveness`) puis rejoue `workflow.advance` (`_run_chain`) — un run mort
non-`completed` route vers la transition CRASH, la seule qui subsiste.
Prédicats (`is_manager_parent`/`should_wake_parent`/`children_signature`) purs."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

from ... import close_reasons
from ...runtime import deferred as web_deferred
from ...runtime import ipc
from ...runtime import runner
from ..sessions import store
from . import closure_guard, projects, reaper, wake_digest, workflow
from . import tickets as tickets_svc

_log = logging.getLogger(__name__)

WAKE_STATE_PATH = Path.home() / ".bouzecode" / "web_v2" / "wake_state.json"
_POLL_INTERVAL = 8  # secondes entre deux ticks du filet de sécurité (si activé)

# close_reasons GRACIEUX = ceux qui autorisent le reconciler à marquer le run `completed`.
# Le reconciler DOIT recouvrir tout ce que la boucle produit de propre, sinon un agent qui a
# fini PROPREMENT mais dont le callback /completed est perdu n'est jamais réconcilié. Bug
# observé (ticket T6) : 'final_answer_deferred' était omis → ticket bloqué 'à relire' malgré
# un commit prêt. Même trou rouvert le 2026-07-29 avec 'final_answer_over_failed_tool'.
# La table vit désormais dans web_v2/close_reasons.py, partagée avec `runner` et `liveness` —
# trois ensembles séparés étaient exactement la cause. Anti-divergence : tests/web_v2/
# test_close_reasons_table.py (toute raison assignée par la boucle doit y être classée).
GRACEFUL_CLOSE_REASONS = close_reasons.ADVANCING_CLOSE_REASONS


def _is_work_abandoned_mid_turn(run: dict, close_reason: str) -> bool:
    """Un run de TRAVAIL (`kind=="work"`) clos sur `text_no_tools` = l'agent codeur a fini
    un tour sur du TEXTE, sans tool_calls ni FinalAnswer : arrêt EN PLEIN MILIEU, AUCUNE
    livraison. `text_no_tools` est classé gracieux car LÉGITIME pour un run `validate`/`manager`
    (le verdict est dans le texte), mais ILLÉGITIME pour un run `work` — on ne doit ni le marquer
    `completed` ni avancer vers le test-gate/validateur : c'est un CRASH fonctionnel, pas une
    complétion. Cible EXCLUSIVEMENT `kind=="work"` (les autres kinds gardent la clôture gracieuse)."""
    return str((run or {}).get("kind", "")) == "work" and close_reason == "text_no_tools"


# ── Prédicats purs ──────────────────────────────────────────────────────────

def is_manager_parent(parent: str) -> bool:
    """Un parent réveillable est un agent manager (agent_id), pas un tag dispatcher
    ('dispatcher:manual', 'dispatcher:validate', …) ni l'absence de parent."""
    return bool(parent) and not parent.startswith("dispatcher:")


def _work_run(ticket: dict) -> dict | None:
    """Le run 'work' du ticket (le plus récent), ou None."""
    return next((r for r in ticket.get("runs") or []
                 if isinstance(r, dict) and r.get("kind") == "work"), None)


def work_delivered(ticket: dict) -> bool:
    """Vrai quand l'enfant a LIVRÉ : il a un run de travail et plus rien ne tourne.

    Sans chaîne automatique, plus aucun validateur ni merge n'arrivera derrière le
    travail pour rendre le ticket terminal : la livraison EST l'issue de l'enfant. Sans
    ce prédicat, `terminal_outcome` resterait None à vie et le manager parent ne serait
    JAMAIS réveillé — or c'est justement lui qui doit maintenant décider de la suite.

    PRÉDICAT WAKE-LOCAL et PUR (pas d'I/O) : on ne touche PAS `reaper.terminal_outcome`,
    le faucheur ne doit pas moissonner ces worktrees pour autant (le travail livré reste
    à relire, à valider ou à intégrer)."""
    if workflow.derive_state(ticket) == "busy":
        return False
    return _work_run(ticket) is not None


def launch_failed(ticket: dict) -> bool:
    """Le PROVISIONNEMENT de cet enfant a échoué : aucun agent n'a jamais démarré (drapeau
    `launch_failed` posé par `dispatch.record_launch_failure`). C'est un enfant TERMINÉ EN
    ÉCHEC, pas un enfant en cours : il n'a ni run, ni worktree, et rien ne le reprendra."""
    return bool(ticket.get("launch_failed"))


def launch_failure_label(ticket: dict) -> str:
    """Étiquette d'issue d'un lancement échoué, pour le digest du parent. PURE et STABLE
    (lue par `children_signature` : toute variation dans le temps re-réveillerait en boucle)."""
    info = ticket.get("launch_failed")
    error = str((info.get("error") if isinstance(info, dict) else "") or "")[:300]
    return ("ÉCHEC DE LANCEMENT — aucun agent n'a démarré, RIEN n'a été fait"
            + (f" : {error}" if error else ""))


def ticket_terminal(ticket: dict) -> bool:
    """Vrai quand le ticket a atteint une ISSUE terminale pour le RÉVEIL DU PARENT.

    AUTORITÉS (deux, chacune documentée) :
    - `reaper.terminal_outcome`, la MÊME que le faucheur, pour ne JAMAIS diverger sur les
      issues classiques (crashé, mergé, merge bloqué) ;
    - `work_delivered` (WAKE-LOCAL) : le travail est fini et plus rien ne l'enchaîne
      automatiquement → l'enfant a rendu sa copie, le parent doit être réveillé.

    Un run encore actif (busy) n'est jamais terminal."""
    if workflow.derive_state(ticket) == "busy":
        return False
    # Lancement échoué : aucun agent n'a démarré et plus rien ne le reprendra — c'est une
    # ISSUE (en échec), pas une attente. Sans cette clause le parent attendait à vie.
    if launch_failed(ticket):
        return True
    if reaper.terminal_outcome(ticket) is not None:
        return True  # mergé / KO-plafonné / planté : une issue, MÊME ré-instruit (cf. ci-dessous)
    # RÉ-INSTRUIT, réponse pas encore rendue : PAS une issue. Entre le `MessageAgent` du
    # manager et le premier tour observable de l'enfant, le process n'est pas encore vu
    # `running` : `derive_state` renvoie encore work_done, l'enfant repassait donc terminal
    # avec la MÊME issue qu'avant — et la branche `elif` de `process_wakes` clôturait le
    # manager qui attendait justement cette réponse (maillon 3 du cercle vicieux). Ce drapeau
    # est posé par `messaging.send_to_ticket_agent` et retiré par `tickets.mark_run_completed`
    # (le tour clos EST la réponse) : il ne peut pas geler le parent, un enfant qui meurt sans
    # reclore repasse par `crashed`, capté par la clause `terminal_outcome` ci-dessus.
    if child_awaiting_reply(ticket):
        return False
    return work_delivered(ticket)


def child_awaiting_reply(ticket: dict) -> bool:
    """L'enfant a été RÉ-INSTRUIT et n'a pas encore reclos de tour depuis. Pur, zéro I/O."""
    return bool(ticket.get(tickets_svc.AWAITING_REPLY_KEY))


def ticket_outcome(ticket: dict) -> str:
    """Étiquette d'issue d'un enfant pour le digest parent, ALIGNÉE sur `terminal_outcome`
    (même autorité que le réveil/faucheur). Distingue explicitement OK / KO(failed) / CRASHED.
    Ticket pas encore terminal : dernier verdict connu, sinon statut dérivé."""
    outcome = reaper.terminal_outcome(ticket)
    if outcome == "crashed":
        return "CRASHED"
    if outcome == "integrated":
        return "OK (éphémère, non mergé)" if ticket.get("ephemeral") else "OK (mergé)"
    if outcome == "needs_attention":
        return "MERGE BLOQUÉ (arbre principal sale/conflit non auto-résolu) — à réintégrer"
    if launch_failed(ticket):
        return launch_failure_label(ticket)
    # Un verdict de validateur (spawné à la demande) prime : c'est l'info la plus riche.
    for run in ticket.get("runs") or []:
        if isinstance(run, dict) and str(run.get("kind", "")).startswith("validate") and run.get("verdict"):
            return run["verdict"]
    # Terminal WAKE-LOCAL : travail livré, rien ne l'enchaîne → le verdict est dans le rapport
    # de l'agent. Étiquette FIXE = PURE (children_signature en dépend : toute I/O ici rendrait
    # la signature instable → re-réveil en boucle).
    if work_delivered(ticket):
        return "travail LIVRÉ (non validé, non mergé) — verdict dans le rapport de l'agent"
    return tickets_svc.derive_status(ticket)


def has_launched(ticket: dict) -> bool:
    """Un enfant lancé porte ≥1 run ; un orphelin (jamais lancé) est ignoré au réveil."""
    runs = ticket.get("runs")
    return isinstance(runs, list) and len(runs) > 0


def child_counts_for_wake(ticket: dict) -> bool:
    """Cet enfant PÈSE-t-il dans le réveil du parent ? Oui s'il a été lancé (≥1 run) OU si
    son lancement a ÉCHOUÉ.

    `has_launched` seul écartait le second cas comme un orphelin « jamais lancé » : un manager
    dont le seul enfant échoue au provisionnement n'avait plus « aucun enfant réel », donc
    `should_wake_parent` renvoyait False et il attendait un verdict qui ne viendrait jamais
    (cas 60f34332 du 2026-07-28). Un enfant mort-né est une ISSUE à rapporter au parent, pas
    un non-événement."""
    return has_launched(ticket) or launch_failed(ticket)


def child_pending_launch(ticket: dict) -> bool:
    """Enfant fraîchement (re)dispatché : `launching` posé par set_launching AVANT que
    le premier run n'existe (add_run retire le flag). Un tel enfant n'a pas encore de run
    donc `has_launched` est False et il serait à tort ignoré du critère « tous terminaux » —
    d'où la finalisation prématurée du parent (bug témoin 1b5860ed, enfant redispatché).
    Tant qu'un enfant est en cours de lancement, le parent ne doit PAS être finalisé."""
    return bool(ticket.get("launching"))


def children_signature(child_tickets: list[dict]) -> str:
    """Signature des enfants RÉELS : change quand un enfant a une NOUVELLE issue OU a
    RÉELLEMENT RETRAVAILLÉ ; identique sinon → pas de double réveil.

    LE BUG QU'ELLE CORRIGE. La signature ne portait que l'ISSUE (`ticket_outcome`). Un enfant
    ré-instruit par `MessageAgent` repart, retravaille, re-livre… et retombe sur EXACTEMENT
    la même issue (« travail LIVRÉ »). Signature inchangée → `should_wake_parent` renvoyait
    False : le manager attendait une réponse qui ne le réveillerait JAMAIS (mesuré deux fois
    le 2026-07-29, dont 54 minutes jusqu'à un réveil à la main).

    POURQUOI LE COMPTEUR DE TOURS (`wake_digest.run_turns`) ET RIEN D'AUTRE :
      * il bouge SI ET SEULEMENT SI l'enfant a clos un tour — `tickets.mark_run_completed`
        est le SEUL endroit qui l'incrémente, et c'est déjà LA fonction qui enregistre
        « ce run a fini proprement » (hook /completed + reconciler). Aucun nouveau site
        d'appel, aucune I/O nouvelle ;
      * il est PUR à lire (un entier sur un run déjà chargé) : `children_signature` est
        évaluée pour chaque parent à CHAQUE tick (8 s) et doit le rester — c'est ce qui
        garantit que le coût du tick à vide ne bouge pas ;
      * il est MONOTONE et ÉVÉNEMENTIEL, donc il ne peut pas produire de TEMPÊTE de réveils :
        il n'avance que sur une écriture explicite. C'est exactement ce qui disqualifie les
        candidats voisins — `dead_ticks` (incrémenté à CHAQUE tick sur un agent mort),
        l'horodatage du dernier message (bouge pendant que l'enfant travaille encore, donc
        réveillerait le parent sur un enfant à mi-tour), ou un compteur de tours relu dans la
        session (une ouverture de fichier par enfant et par tick).
      * `len(runs)` NE SUFFIT PAS et c'est le cœur du cas mesuré : une ré-instruction par
        `MessageAgent` réutilise le MÊME run (`continue_agent`, contexte gardé), elle ne crée
        aucun run. Le compteur de tours couvre les deux : relance (nouveau run, turns repart)
        et ré-instruction (même run, turns +1)."""
    return ";".join(f"{t['id']}:{ticket_outcome(t)}#t{wake_digest.run_turns(t)}"
                    for t in sorted(child_tickets, key=lambda t: t["id"])
                    if child_counts_for_wake(t))


def child_blocked_on_question(ticket: dict) -> bool:
    """Un enfant lancé dont le run ATTEND une réponse (question posée). Il n'est PAS
    terminal (busy), donc sans ce prédicat il bloquerait à jamais le réveil du parent :
    la question resterait orpheline (personne pour y répondre)."""
    return has_launched(ticket) and ticket_outcome(ticket) == "attend réponse"


def should_wake_parent(parent_finished: bool, child_tickets: list[dict],
                       last_signature: str | None, current_signature: str) -> bool:
    """Réveil (pur) : le manager a fini, ≥1 enfant réel, verdicts neufs, ET soit TOUS
    les enfants terminaux, soit ≥1 enfant BLOQUÉ sur une question (à qui répondre)."""
    if not parent_finished:
        return False
    # Un enfant en cours de lancement (launching, pas encore de run) doit bloquer le réveil :
    # sinon le parent est finalisé avant même que l'enfant redispatché ne démarre.
    if any(child_pending_launch(t) for t in child_tickets):
        return False
    real = [t for t in child_tickets if child_counts_for_wake(t)]
    if not real:
        return False
    all_terminal = all(ticket_terminal(t) for t in real)
    any_blocked = any(child_blocked_on_question(t) for t in real)
    if not (all_terminal or any_blocked):
        return False
    return current_signature != last_signature


def build_wake_digest(child_tickets: list[dict]) -> str:
    launched = [t for t in sorted(child_tickets, key=lambda t: t["id"])
                if child_counts_for_wake(t)]
    awaiting = [t for t in launched if ticket_outcome(t) == "attend réponse"]
    stillborn = [t for t in launched if launch_failed(t)]
    lines = [
        "Tous tes enfants ont fini leur tour. Digest des verdicts :",
        "(Rappel : cette relance automatique est le protocole normal — tu avais correctement "
        "clos ton tour en attente. Clore n'abandonne jamais la mission ; le système te réveille "
        "à chaque fin d'enfant. Après avoir traité ce digest, re-clos ton tour : tu seras à "
        "nouveau réveillé si nécessaire. Ne boucle jamais sur Fleet(list)/Methodology pour surveiller.)",
        "",
    ]
    # Une ligne d'issue NE SUFFIT PAS à décider : le manager redemandait le détail par
    # message, et cette ré-instruction ne le réveillait plus jamais. Chaque enfant arrive
    # donc avec sa PREUVE (raison de l'échec / de quoi juger la livraison), bornée par
    # `wake_digest` — UNE seule ouverture de session par enfant, et seulement à ce réveil.
    for t in launched:
        lines += wake_digest.child_block(t, delivered=work_delivered(t))
    lines.append("")
    if stillborn:
        ids = ", ".join(t["id"] for t in stillborn)
        lines += [
            f"⛔ Enfant(s) dont le LANCEMENT A ÉCHOUÉ : {ids}. Aucun agent n'a démarré, "
            "AUCUN travail n'a été fait — leur tâche n'a pas commencé, ne la considère "
            "jamais comme faite.",
            "À TOI de décider pour chacun : le relancer (bouton Relancer du ticket, ou "
            "POST /api/tickets/<slug>/<id>/launch), redispatcher la tâche autrement (autre "
            "isolation), ou ESCALADER à l'utilisateur si le motif se répète. Aucune reprise "
            "automatique n'aura lieu.",
            "",
        ]
    if awaiting:
        ids = ", ".join(t["id"] for t in awaiting)
        lines += [
            f"⛔ Enfant(s) BLOQUÉ(S) sur une QUESTION en attente de réponse : {ids}.",
            "Pour CHACUN : soit tu peux TRANCHER seul → réponds-lui via "
            "MessageAgent(ticket_id=<id>, text=<ta réponse>) ; soit tu ne peux PAS trancher "
            "seul → ESCALADE la question à l'utilisateur via AskUserQuestion. Tu ne codes "
            "JAMAIS toi-même et tu ne laisses AUCUN enfant bloqué sans réponse.",
            "",
        ]
    lines += [
        "AUCUNE suite automatique n'est déclenchée : un travail livré n'est ni testé, ni "
        "validé, ni mergé tant que TU ne le demandes pas. À toi de décider, pour chaque "
        "enfant livré : le relancer avec des objections (MessageAgent), lui spawner un "
        "validateur (Agent), ou intégrer sa branche.",
        "Synthétise ensuite : si tout est OK, rends le VERDICT FINAL agrégé et termine par "
        "une ligne 'VERDICT: OK'. Si un enfant est KO ou CRASHED, redispatche un Agent pour "
        "la seule tâche en échec (avec le contexte de l'échec) puis re-termine ton tour. "
        "Ne rends 'VERDICT: OK' QUE lorsque plus aucun enfant n'est bloqué ni en échec.",
    ]
    return "\n".join(lines)


# ── État persistant (idempotence) ───────────────────────────────────────────

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


# ── Réveil + filet de sécurité ────────────────────────────────────────────────

def _close_reason_with_ipc_fallback(agent, session_close_reason: str) -> str:
    """Repli IPC pour la clôture gracieuse. La session DISQUE fait foi quand elle
    porte un close_reason ; mais le bug racine (stamp session manquant à la clôture
    gracieuse) laissait la session VIDE alors que l'IPC state.json portait
    {status:finished, close_reason:final_answer}. Dans ce cas on lit l'IPC en repli :
    si l'IPC prouve une clôture gracieuse (finished + close_reason non vide), on la
    renvoie ; sinon on garde la valeur session (vide → mort non gracieuse). Agent
    déchargé (None) ou IPC absent/non-finished → on garde la session telle quelle."""
    if session_close_reason:
        return session_close_reason
    if agent is None:
        return session_close_reason
    ipc_dir = getattr(agent, "ipc_dir", "") or ""
    if not ipc_dir:
        return session_close_reason
    state = ipc.read_state(ipc.from_dir(ipc_dir))
    if state.get("status") != ipc.STATUS_FINISHED:
        return session_close_reason
    return state.get("close_reason") or session_close_reason


def _reconcile_graceful_close(slug: str, ticket: dict) -> None:
    """Rejoue une clôture gracieuse dont le callback `/completed` a été PERDU (serveur
    down/redémarré, ou hook non-firé au moment où l'agent a fini). Un run dont le process
    est mort, non `completed`, sans verdict, mais dont la session DISQUE porte un
    `close_reason` GRACIEUX (`GRACEFUL_CLOSE_REASONS` : final_answer / final_answer_deferred
    / text_no_tools) a terminé PROPREMENT : on le marque `completed` pour qu'`advance()`
    prenne la branche normale (validate/merge) au lieu de la transition CRASH. Sans ça, un
    manager/coder qui finit pendant un redémarrage serveur est faussement marqué « planté »
    (son verdict n'est pas re-parsé : `manager` n'est pas dans _VERDICT_TYPOLOGIES)."""
    for run in ticket.get("runs") or []:
        if not isinstance(run, dict) or run.get("completed") or run.get("verdict"):
            continue
        agent_id = run.get("agent_id", "") or ""
        if not agent_id:
            continue
        agent = runner.load_agent(agent_id)
        if agent and runner.is_running(agent):
            continue  # process encore vivant → laisser le flux normal (push /completed)
        # agent mort OU déchargé (nettoyé après mort) : la session DISQUE fait foi.
        # session_path reconstruit depuis AGENTS_DIR pour rester lisible même agent déchargé.
        session_path = getattr(agent, "session_path", "") or ""
        if not session_path:
            session_path = str(runner.AGENTS_DIR / f"{agent_id}.session.json")
        data = store.load_session_json(Path(session_path)) or {}
        # Repli IPC : le bug racine laissait la session VIDE à la clôture gracieuse
        # alors que l'IPC portait close_reason=final_answer. On lit l'IPC en repli
        # pour ne PAS traiter une clôture gracieuse (IPC=finished) comme un crash.
        close_reason = _close_reason_with_ipc_fallback(agent, data.get("close_reason") or "")
        # Un run WORK clos sur text_no_tools = arrêté en plein milieu (pas de FinalAnswer) :
        # NE PAS marquer completed / avancer vers le validateur — router vers la transition
        # CRASH comme une mort non-gracieuse. text_no_tools reste gracieux pour validate/manager.
        if _is_work_abandoned_mid_turn(run, close_reason):
            workflow._act_report_crash(slug, ticket, "")
            continue
        # Garde MANAGER : un manager/monitor (NON_CODING_TYPOLOGIES) rend une FinalAnswer
        # à CHAQUE tour (obligation harness) → close_reason gracieux. Mais FinalAnswer d'un
        # tour ≠ fin de mission tant qu'un enfant est encore actif : le manager doit rester
        # RÉVEILLABLE (process_wakes le relancera quand l'enfant finira). Le stamper
        # `completed` ici le fige « Terminé » et gèle l'orchestration (enfant jamais
        # supervisé/relancé). On ne le marque completed QUE si aucun enfant n'est actif —
        # alors _finalize_noncoding_parent le clôturera proprement via process_wakes.
        if (ticket.get("typology") or "") in workflow.NON_CODING_TYPOLOGIES:
            children = _children_by_parent().get(run["agent_id"], [])
            if any(child_pending_launch(t) or (has_launched(t) and not ticket_terminal(t))
                   for t in children):
                continue
        if close_reason in GRACEFUL_CLOSE_REASONS:
            # Gate: a `final_answer_deferred` close still has queued deferred checks
            # (e.g. an Azure deploy) that the runner drains AFTER the process exits. Do
            # NOT mark completed / advance to validate/merge while <session>.deferred.json
            # exists — the drain deletes it only once every check is green. Plain closes
            # (final_answer / text_no_tools) never write a deferred file → no-op for them.
            if web_deferred.exists(session_path):
                continue
            tickets_svc.mark_run_completed(slug, ticket, run["agent_id"])
            # Clôture GRACIEUSE reconstruite → le `crashed` posé par le watchdog pendant la
            # fenêtre process-mort/stamp était un FAUX crash : on le retire pour qu'`advance()`
            # prenne la branche normale et que le ticket cesse d'afficher « planté » (cas 86c37f5a).
            ticket.pop("crashed", None)
            tickets_svc.update_ticket(slug, ticket)  # persiste le retrait (mark_run_completed n'écrit que `completed`)


def _reconcile_api_crash(slug: str, ticket: dict) -> None:
    """Symétrique de `_reconcile_graceful_close` pour une mort API. Un run dont le process
    est mort, non `completed`, sans verdict, mais dont la session DISQUE porte un
    `close_reason == "api_error"` (panne provider après épuisement des retries) a été tué
    par l'infra, PAS terminé proprement : on route DIRECTEMENT vers la transition CRASH
    (`workflow._act_report_crash`) au lieu de laisser le ticket geler en `awaiting_verdict`
    (verdict None non-actionnable) jusqu'au watchdog. Idempotent (déjà `crashed` → no-op)."""
    from . import workflow
    for run in ticket.get("runs") or []:
        if not isinstance(run, dict) or run.get("completed") or run.get("verdict"):
            continue
        agent_id = run.get("agent_id", "") or ""
        if not agent_id:
            continue
        agent = runner.load_agent(agent_id)
        if agent and runner.is_running(agent):
            continue  # process encore vivant → laisser le flux normal
        session_path = getattr(agent, "session_path", "") or ""
        if not session_path:
            session_path = str(runner.AGENTS_DIR / f"{agent_id}.session.json")
        data = store.load_session_json(Path(session_path)) or {}
        if data.get("close_reason") == "api_error":
            workflow._act_report_crash(slug, ticket, "")
            return


def _reconcile_resolved_conflicts(slug: str, ticket: dict) -> None:
    """Un ticket en conflit de merge dont le résolveur (le codeur relancé) a fini est
    RÉ-INTÉGRÉ automatiquement — sinon le conflit résolu resterait coincé, l'état 'merge'
    n'ayant pas de transition dans la machine à états. `resume_after_conflict` no-op si le
    résolveur tourne encore."""
    if not isinstance(ticket, dict):
        return
    meta = ticket.get("worktree")
    if not isinstance(meta, dict) or meta.get("state") != "conflict":
        return
    from . import integration  # import différé : évite un cycle wake <-> integration
    integration.resume_after_conflict(slug, ticket)


_CRASH_DEAD_TICKS = 2  # debounce : nb d'observations mortes CONSÉCUTIVES avant de déclarer un crash


def crash_is_contradicted(ticket: dict, any_agent_live: bool) -> bool:
    """Le drapeau `crashed` du ticket est-il DÉMENTI par les faits ? (pur)

    `crashed` est TERMINAL : `derive_status`/`derive_state` le testent EN PREMIER, donc un
    drapeau périmé masque tout le reste. Or il n'était retiré que par `add_run` — et un
    manager repris par message ne crée AUCUN run sur SON ticket (l'enfant a le sien) : le
    drapeau restait collé à vie et le board affichait « planté » un agent en pleine activité
    (cas observé beefcafe, agent 0123456789ab relancé, livré, puis re-dispatché).

    On le démentit sur les deux preuves qui font TOMBER la garde `workflow._is_crash` ayant
    servi à le poser :
      - un process d'agent du ticket est de nouveau VIVANT (l'agent a été repris) ;
      - le run le plus récent porte `completed` ou un `verdict` : il a LIVRÉ depuis.
    Un agent réellement mort n'a ni l'une ni l'autre — son drapeau reste posé."""
    if not ticket.get("crashed"):
        return False
    if any_agent_live:
        return True
    newest = next((r for r in ticket.get("runs") or [] if isinstance(r, dict)), None)
    return bool(newest and (newest.get("completed") or newest.get("verdict")))


def _stamp_liveness(slug: str, ticket: dict) -> None:
    """RECONCILER : stampe `run['pid_alive']` (psutil, via runner.is_running) — entrée IMPURE
    du prédicat pur `workflow._is_crash`. Champ pid_alive TRANSITOIRE (non persisté).

    DEBOUNCE : `runner.is_running` peut renvoyer False FUGACEMENT (agent REPRIS entre deux tours
    pendant un continue_coder, hoquet psutil). Un seul False ne condamne PAS : on compte
    `dead_ticks` (lui PERSISTÉ, car pid_alive ne l'est pas) et on ne pose pid_alive=False
    (→ is_crash → crash collant + reap) qu'après _CRASH_DEAD_TICKS morts CONSÉCUTIFS. Vu vivant
    → compteur remis à 0. Sinon un faux positif transitoire fauche un agent bien vivant."""
    live_by_run: dict[int, bool] = {}
    dirty = False
    for run in ticket.get("runs") or []:
        if not isinstance(run, dict):
            continue
        agent = runner.load_agent(run.get("agent_id", "") or "")
        live = bool(agent and runner.is_running(agent))
        live_by_run[id(run)] = live
        prev = int(run.get("dead_ticks") or 0)
        new = 0 if live else prev + 1
        if new != prev:
            run["dead_ticks"] = new
            dirty = True
    # Symétrie du debounce : le même passage qui CONSTATE la mort doit RÉVOQUER un crash
    # démenti, sinon le drapeau survit à la résurrection de l'agent (cf. crash_is_contradicted).
    if crash_is_contradicted(ticket, any(live_by_run.values())):
        ticket.pop("crashed", None)
        dirty = True
    if dirty:
        try:
            tickets_svc.update_ticket(slug, ticket)  # dead_ticks doit survivre entre ticks
        except (OSError, sqlite3.Error) as exc:
            # Persistance best-effort du compteur de liveness. Le store est désormais SQLite
            # (WAL) : une écriture peut rarement échouer sous forte contention inter-process
            # (serveur + N agents CLI), typiquement sqlite3.OperationalError malgré busy_timeout.
            # Ce n'est PAS un échec du ticket : dead_ticks est recalculé au tick suivant. On log
            # en DEBUG pour ne pas polluer les logs Flask avec une traceback ERROR "ticket ... a échoué".
            _log.debug("wake._stamp_liveness[%s]: persist dead_ticks best-effort échouée: %s",
                       slug, exc)
    for run in ticket.get("runs") or []:  # pid_alive transitoire, posé APRÈS le debounce
        if isinstance(run, dict):
            live = live_by_run.get(id(run), False)
            run["pid_alive"] = live or int(run.get("dead_ticks") or 0) < _CRASH_DEAD_TICKS


def _run_chain(slug: str, rows: list[dict]) -> None:
    """Filet de sécurité + reconciler crash-aware IDEMPOTENT : stampe la vivacité puis
    rejoue `workflow.advance` ticket par ticket. Un run mort non-`completed` route vers la
    transition CRASH (jamais un merge). Résilient par-ticket. Appelé par la route liste ET
    le watchdog, donc un crash est capté au plus tôt (pas seulement au tick du poller)."""
    for ticket in rows:
        try:
            if isinstance(ticket, dict):
                _reconcile_graceful_close(slug, ticket)  # rejoue un /completed perdu (serveur down)
                _reconcile_api_crash(slug, ticket)  # mort API → crash immédiat (pas d'awaiting_verdict éternel)
                _reconcile_resolved_conflicts(slug, ticket)  # ré-intègre un conflit résolu par le codeur
                _stamp_liveness(slug, ticket)
            workflow.advance(slug, ticket)
            if isinstance(ticket, dict):
                reaper.reap_ticket(slug, ticket)  # GC : un ticket devenu terminal est fauché
        except Exception:  # noqa: BLE001 — résilience par-ticket, jamais silencieuse
            _log.exception("wake._run_chain: ticket %s du projet %s a échoué",
                           ticket.get("id") if isinstance(ticket, dict) else ticket, slug)


def _children_by_parent() -> dict[str, list[dict]]:
    """Regroupe les tickets (tous projets) par manager parent, états de runs frais.
    Résilient par-projet : un projet dont le refresh échoue est loggé et sauté.

    Le filtrage par parent se fait AVANT le refresh : seuls les enfants d'un manager
    pèsent dans le réveil, or on rafraîchissait TOUS les tickets du projet — une lecture
    de fichier agent par run, pour des tickets aussitôt jetés. Le résultat est identique
    (mêmes tickets, même fraîcheur) ; c'est le travail jeté qui disparaît."""
    by_parent: dict[str, list[dict]] = {}
    for project in projects.list_projects():
        try:
            children = [t for t in tickets_svc.list_tickets(project["slug"])
                        if is_manager_parent(t.get("parent") or "")]
            if not children:
                continue
            tickets_svc.refresh_verdicts(project["slug"], children)
        except Exception:  # noqa: BLE001 — un projet cassé ne tue pas le regroupement
            _log.exception("wake._children_by_parent: projet %s a échoué", project.get("slug"))
            continue
        for ticket in children:
            by_parent.setdefault(ticket["parent"], []).append(ticket)
    return by_parent


def _finalize_noncoding_parent(parent_agent, kids: list[dict] | None = None) -> bool:
    """Clôt le ticket d'un manager/monitor (read-only) : il n'a ni validateur ni merge pour
    le marquer terminal (cf. workflow.NON_CODING_TYPOLOGIES), donc sans ça il resterait « en
    attente des enfants » à vie et s'empilerait. Marque `done` + fauche. No-op si déjà done,
    ticket introuvable, ou typologie codante (le codeur garde son test-gate/merge).

    `kids` = les tickets enfants DÉJÀ chargés par `process_wakes` (aucune requête de plus),
    soumis au garde-fou de clôture (`closure_guard`). Défaut None = « pas d'enfant connu » :
    le comportement historique, pour les appelants qui ne supervisent pas d'enfants."""
    slug, tid = parent_agent.ticket_slug, parent_agent.ticket_id
    if not (slug and tid):
        return False
    ticket = tickets_svc.get_ticket(slug, tid)
    if ticket is None or ticket.get("done"):
        return False
    if (ticket.get("typology") or "") not in workflow.NON_CODING_TYPOLOGIES:
        return False
    # Un manager réellement PLANTÉ ne doit pas être clos en « terminé » : laisser le crash
    # visible (« planté » = en attente d'action) plutôt que le masquer par un done automatique.
    if ticket.get("crashed"):
        return False
    # Un manager qui rend « VERDICT: KO » refuse explicitement la clôture : le routage n'est
    # pas concluant (ex. il vient de redispatcher un enfant). Ne PAS le stamper done — il reste
    # « en attente des enfants » (ou basculera en échec de validation si plus d'enfant actif).
    work_run = _work_run(ticket)
    if work_run and work_run.get("verdict") == "KO":
        return False
    # GARDE-FOU DE CLÔTURE. Jusqu'ici la SEULE barrière de qualité était le verdict
    # AUTO-DÉCLARÉ du manager, ci-dessus : un manager pouvait rendre « VERDICT: OK » alors
    # qu'un enfant était mort sans écrire une ligne (cas beefcafe / enfant deadbeef) et se
    # faire stamper `done` ici — parce que `ticket_terminal` compte `crashed` comme une issue
    # terminale VALIDE. On consulte donc la LIVRAISON des enfants, pas seulement leur
    # terminalité. Pur (dicts déjà chargés), trace posée une seule fois, forçable à la main
    # via POST .../done (cf. closure_guard).
    if closure_guard.refuse_closure(slug, ticket, list(kids or ())):
        return False
    ticket["done"] = True
    tickets_svc.update_ticket(slug, ticket)
    reaper.reap_ticket(slug, ticket)
    return True


# Parents dont le worktree a disparu (fauché/nettoyé) : inutiles à jamais (un resume crasherait
# sur un cwd invalide). Mémorisés pour ne PLUS les recharger ni relogger à chaque tick — sinon
# des dizaines de morts inondaient le log et faisaient N lectures disque par cycle (cf. lenteur).
_dead_cwd_parents: set[str] = set()


def process_wakes() -> list[str]:
    """Réveille les managers dont tous les enfants sont terminaux. Renvoie les
    agent_id réveillés (pour les logs/tests d'intégration)."""
    state = _load_wake_state()
    woken: list[str] = []
    for parent_id, kids in _children_by_parent().items():
        if parent_id in _dead_cwd_parents:
            continue  # worktree évaporé, définitivement ignoré (pas d'I/O ni de log répété)
        # RÉSILIENCE PAR-PARENT : un parent cassé (worktree cwd disparu, agent illisible…)
        # ne doit JAMAIS faire tomber tout le tick — sinon une seule reprise impossible gèle
        # le wake ET toute requête qui le déclenche (dispatch, advance). Loggé, jamais avalé.
        try:
            parent_agent = runner.load_agent(parent_id)
            if parent_agent is None:
                continue
            # Worktree du parent évaporé (fauché/nettoyé) : le resumer crasherait sur un cwd
            # invalide (subprocess.Popen → NotADirectoryError). On le mémorise + saute (log 1×).
            if parent_agent.cwd and not Path(parent_agent.cwd).is_dir():
                _log.warning("wake: parent %s a un cwd disparu (%s) — ignoré désormais", parent_id, parent_agent.cwd)
                _dead_cwd_parents.add(parent_id)
                continue
            parent_finished = store.agent_status(parent_agent)["state"] == "finished"
            signature = children_signature(kids)
            if should_wake_parent(parent_finished, kids, state.get(parent_id), signature):
                runner.continue_agent(parent_agent, build_wake_digest(kids))
                state[parent_id] = signature
                woken.append(parent_id)
            elif (parent_finished and state.get(parent_id) == signature
                  and not any(child_pending_launch(t) for t in kids)
                  and [t for t in kids if child_counts_for_wake(t)]
                  and all(ticket_terminal(t) for t in kids if child_counts_for_wake(t))):
                # Réveil final déjà délivré (signature enregistrée) + manager reclos + TOUS les
                # enfants terminaux : le routage est vraiment fini → clôturer le ticket manager.
                # `kids` est passé pour que le garde-fou de clôture juge la LIVRAISON des
                # enfants sans recharger un seul ticket (ils sont déjà là).
                _finalize_noncoding_parent(parent_agent, kids)
        except Exception:  # noqa: BLE001 — un parent cassé ne tue pas le tick des autres
            _log.exception("wake.process_wakes: parent %s a échoué", parent_id)
    if woken:
        _save_wake_state(state)
    return woken


def ticket_needs_watchdog(ticket: dict) -> bool:
    """Le WATCHDOG a-t-il encore quelque chose à réconcilier sur ce ticket ?

    PUR et SANS AUCUNE I/O PAR RUN : ne lit que la ligne DÉJÀ chargée du store — ni
    `runner.load_agent`, ni ouverture de session. C'est tout l'intérêt : `refresh_verdicts`
    coûte UNE lecture de fichier agent PAR RUN (mesuré sur le store réel : 104 runs →
    5,7 s à froid, 0,29 s à chaud) et le watchdog la payait pour TOUS les tickets toutes
    les 8 s, serveur inactif et navigateur fermé.

    POURQUOI LE FILET DE SÉCURITÉ RESTE SÛR — un ticket écarté ici ne peut RIEN déclencher :
    - CRASH (LA garantie à ne pas perdre) : `workflow._is_crash` exige que le run le PLUS
      RÉCENT soit ni `completed` ni porteur d'un verdict. La clause « run ouvert » ci-dessous
      retient TOUT ticket qui a un tel run — donc tout candidat au crash (agent tué, hook
      `on_completion` non-firé, mort API) reste examiné à CHAQUE tick, exactement comme avant.
    - `_reconcile_graceful_close` / `_reconcile_api_crash` sautent explicitement les runs
      `completed` ou porteurs d'un verdict : sur un ticket écarté ils sont des no-op par
      construction, pas par pari.
    - `_stamp_liveness` n'existe que pour alimenter `_is_crash` : sans candidat au crash, il
      n'écrirait que des `dead_ticks` que plus personne ne lit.
    - `workflow.advance` : aucune transition ne part d'un état hors de la table (clause « état
      actionnable », dérivée de `workflow.TRANSITIONS` elle-même → pas de liste à maintenir).
    - `reaper.reap_ticket` : couvert par la clause « à faucher ».
    Enfin un ticket ne peut redevenir chaud que par une ÉCRITURE dans le store (nouveau run,
    dispatch, verdict, conflit de merge) — et chacune de ces écritures rallume une clause."""
    if ticket.get("launching"):
        return True  # spawn en vol : le run va apparaître, le ticket est actif
    if ticket.get("crashed"):
        # Un crash est RÉVOCABLE (`crash_is_contradicted`) : tant que le drapeau est posé, le
        # ticket doit rester observé. Sans cette clause il sortait du filtre exactement quand
        # la preuve du contraire apparaissait (run `completed`/`verdict` → aucune autre clause
        # ne le retenait) et restait « planté » à vie. Coût nul en pratique : les crashés dont
        # le run est encore ouvert étaient DÉJÀ retenus par la clause suivante, et ceux que
        # cette clause ajoute perdent leur drapeau au tick suivant — la clause s'auto-éteint
        # (mesuré sur le store réel : 3 tickets concernés sur 1334).
        return True
    for run in ticket.get("runs") or []:
        if not isinstance(run, dict):
            continue
        # Comptabilité du run NON CLOSE : candidat crash / `/completed` perdu / api_error.
        if not run.get("completed") and run.get("verdict") is None:
            return True
        # Verdict encore à parser sur un run qui en porte un (validate*, review, manager) :
        # même garde que `refresh_verdicts`, donc aucun verdict ne peut être manqué.
        if tickets_svc._run_carries_verdict(run):
            return True
    meta = ticket.get("worktree")
    if isinstance(meta, dict) and meta.get("state") == "conflict":
        return True  # `_reconcile_resolved_conflicts` doit pouvoir ré-intégrer
    # États d'où une transition PEUT partir, lus dans la table à chaque appel (un plugin
    # peut fournir la sienne) : ajouter une transition ré-arme le filtre automatiquement.
    if workflow.derive_state(ticket) in {tr.state for tr in workflow.TRANSITIONS}:
        return True
    # Reste le GC : seul un ticket mergé ou éphémère est réellement fauché par reap_ticket.
    return reaper.should_reap(ticket) and (
        reaper.terminal_outcome(ticket) == "integrated" or bool(ticket.get("ephemeral")))


def tick() -> None:
    """Un cycle du WATCHDOG (reconciler crash-aware) : par projet, `_run_chain` stampe la
    vivacité (pid_alive) puis rejoue `workflow.advance` — un run mort non-`completed`
    déclenche la transition CRASH (report_crash). Puis réveille les parents.

    La réconciliation n'est payée QUE pour les tickets que `ticket_needs_watchdog` retient.
    Le tri se fait sur une simple lecture du store (SQLite), sans rouvrir un seul fichier
    agent : un projet dont tous les tickets ont fini leur comptabilité ne coûte plus rien."""
    for project in projects.list_projects():
        slug = project["slug"]
        try:
            pending = [t for t in tickets_svc.list_tickets(slug) if ticket_needs_watchdog(t)]
            if not pending:
                continue  # rien à réconcilier : aucune session, aucun fichier agent n'est lu
            # Refresh CIBLÉ. `persist` reste à son défaut (True) : le watchdog est un chemin
            # AUTORITATIF, il doit continuer à persister les verdicts qu'il parse — c'est le
            # chemin de LECTURE (compteurs home) qui doit rester en persist=False. Passer un
            # SOUS-ENSEMBLE est sans danger : `refresh_verdicts` n'écrit QUE les tickets dont
            # un verdict a changé, et via `_mutate` (une ligne, version fraîche relue).
            tickets_svc.refresh_verdicts(slug, pending)
            _run_chain(slug, pending)
        except Exception:  # noqa: BLE001 — un projet cassé ne tue pas le cycle
            _log.exception("wake.tick: projet %s a échoué", project.get("slug"))
    process_wakes()
    _sweep_warm_pool()


def _sweep_warm_pool() -> None:
    """Balayage GLOBAL du warm-pool, à CHAQUE tick — hors de la boucle par projet.

    `fleet.sweep_warm_pool` est aussi appelé sur `POST /api/dispatch` (moment causal : un
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


_poller_started = False
_poller_lock = threading.Lock()


def start_poller(interval: int = _POLL_INTERVAL) -> None:
    """WATCHDOG serveur (reconciler crash-aware), ACTIF PAR DÉFAUT. La chaîne nominale
    reste poussée par les hooks on_completion ; ce poller est le chemin nominal pour les
    CRASHES (agent mort / hook non-firé, indétectables par le modèle push). Opt-out via
    BOUZECODE_WAKE_POLLER=0."""
    import os
    global _poller_started
    if os.environ.get("BOUZECODE_WAKE_POLLER") == "0":
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
