# [desc] API tickets: créer & lancer, follow-up commentaires vers l'agent, validations CI, terminer. [/desc]
from __future__ import annotations

import json
import threading

from flask import Blueprint, Response, jsonify, request

from .._body import json_body

from ...runtime import runner
from ...services.work import (
    closure_guard, dispatch, integration, liveness, messaging, projects, reaper, results,
    tickets, wake, workflow, worktrees,
)

tickets_bp = Blueprint("tickets_api", __name__)


def _project_or_404(slug: str):
    project = projects.find(slug)
    if project is None:
        return None, (jsonify({"error": f"projet inconnu: {slug}"}), 404)
    return project, None


def _ticket_or_404(slug: str, ticket_id: str):
    ticket = tickets.get_ticket(slug, ticket_id)
    if ticket is None:
        return None, (jsonify({"error": f"ticket inconnu: {ticket_id}"}), 404)
    return ticket, None


@tickets_bp.get("/api/projects/<slug>/tickets")
def api_tickets_list(slug: str):
    project, error = _project_or_404(slug)
    if error:
        return error
    include_archived = request.args.get("include_archived") == "1"
    rows = tickets.list_tickets(slug, refresh=True, include_archived=include_archived)
    wake._run_chain(slug, rows)  # résilient par-ticket : un ticket cassé ne 500 plus la route
    # UNE requête pour tout le board : sans elle, `derive_status` annonce « en attente des
    # enfants » à un manager qui n'a jamais rien dispatché (limbo ni actionnable ni terminal).
    parents = tickets.parent_agent_ids(slug)
    # UNE classification de vivacité par ticket, servie au front (`liveness_state`) ET donnée
    # à `derive_status` : le libellé et la vivacité ne peuvent plus se contredire.
    live = {ticket["id"]: liveness.classify_ticket(ticket) for ticket in rows}
    full = request.args.get("full") == "1"
    if full:
        data = [
            {**ticket, "status": tickets.derive_status(
                ticket, parents_with_children=parents, liveness_state=live[ticket["id"]]),
             "liveness_state": live[ticket["id"]]} for ticket in rows
        ]
    else:
        data = [
            {**tickets.ticket_summary(ticket, parents_with_children=parents,
                                      liveness_state=live[ticket["id"]]),
             "liveness_state": live[ticket["id"]]} for ticket in rows
        ]
    return Response(
        json.dumps({"tickets": data}, indent=2, ensure_ascii=False),
        content_type="application/json",
    )


@tickets_bp.get("/api/tickets/<slug>/<ticket_id>")
def api_ticket_detail(slug: str, ticket_id: str):
    project, error = _project_or_404(slug)
    if error:
        return error
    ticket, error = _ticket_or_404(slug, ticket_id)
    if error:
        return error
    # `liveness_state` est servi ICI comme sur la liste (/api/projects/<slug>/tickets) :
    # MÊME classifieur `liveness.classify_ticket`. Le statut dérivé ne peut pas le
    # remplacer — il mélange plusieurs notions (done prime et masque crashed). C'est ce
    # champ, et lui seul, qui autorise l'UI à proposer une RELANCE (crashed/stalled =
    # plus aucun agent vivant), le `.../launch` étant le seul chemin qui re-provisionne
    # l'isolation. `isolation` et `typology` du ticket voyagent déjà dans le `**ticket`
    # : ce sont les valeurs que la relance doit renvoyer telles quelles.
    # État LIVE des runs (`state`) : jamais persisté (cf. tickets.refresh_verdicts), il doit
    # être re-attaché À LA LECTURE, sinon `derive_status` annonce « à relire » un agent qui
    # TOURNE. `persist=False` = chemin de lecture pure, aucune écriture du store.
    tickets.refresh_verdicts(slug, [ticket], persist=False)
    live = liveness.classify_ticket(ticket)
    data = {**ticket, "status": tickets.derive_status(
        ticket, parents_with_children=tickets.parent_agent_ids(slug), liveness_state=live),
        "liveness_state": live}
    return Response(
        json.dumps(data, indent=2, ensure_ascii=False),
        content_type="application/json",
    )


@tickets_bp.post("/api/projects/<slug>/tickets")
def api_tickets_create(slug: str):
    project, error = _project_or_404(slug)
    if error:
        return error
    payload = json_body(request)
    title = (payload.get("title") or "").strip()
    prompt = (payload.get("prompt") or "").strip()
    if not title or not prompt:
        return jsonify({"error": "title et prompt requis"}), 400
    ticket = tickets.create_ticket(slug, title, prompt)
    ticket["parent"] = payload.get("parent") or ""
    tickets.update_ticket(slug, ticket)
    if payload.get("launch", True):
        # Resolve typology → profile. Le défaut `coder` est réservé aux lancements MANAGÉS
        # (parent = agent_id d'un manager) : un ticket créé à la main depuis l'UI et sans
        # typology reste un agent NU, comme en TUI. `managed=` est passé EXPLICITEMENT —
        # l'omettre retombait sur le défaut True de la signature et poussait en silence
        # TOUT ticket web sans typology sur `coder`.
        typology_name = payload.get("typology") or ""
        profile = dispatch.resolve_profile(
            typology_name, project["path"],
            managed=dispatch.is_managed_parent(ticket.get("parent", "")),
        )
        # Isolation DEMANDÉE (shared | worktree | worktree+venv), même garde-fou anti-collision
        # que /api/dispatch : deux agents `shared` sur le même dépôt → le second est isolé.
        isolation, _reason, collision_note = dispatch.resolve_isolation(
            project["path"], payload.get("isolation") or dispatch.SHARED
        )
        # La typology doit être portée par le ticket AVANT le lancement : _launch enregistre
        # le run avec add_run(typology=ticket.get("typology", "")).
        ticket["typology"] = typology_name
        ticket["isolation"] = isolation
        tickets.update_ticket(slug, ticket)
        if collision_note:
            tickets.add_comment(slug, ticket, collision_note, True)
        model = payload.get("model") or ""
        parent = payload.get("parent") or ""
        # ASYNCHRONE PAR DÉFAUT : le POST répond dès le ticket créé (<1 s) ; le provisioning
        # (git worktree add) + spawn agent partent en fond via le mécanisme defer de /api/dispatch
        # (thread _launch_bg, briques _launch/_maybe_isolate qui ne tiennent PAS _tickets_lock
        # pendant git/spawn → les GET restent réactifs, les créations s'enchaînent sans blocage).
        if payload.get("defer", True):
            tickets.set_launching(slug, ticket)
            threading.Thread(
                target=dispatch._launch_bg,
                args=(slug, ticket, project["path"], profile, model, isolation, parent, ""),
                daemon=True,
            ).start()
            return jsonify(ticket)
        # defer=False : chemin SYNCHRONE conservé (non-régression / tests déterministes).
        try:
            dispatch._launch(slug, ticket, project["path"], profile, model,
                             isolation, parent, "")
        except runner.MissingProviderEnvError as exc:
            return jsonify({"error": str(exc)}), 500
    return jsonify(ticket)


@tickets_bp.post("/api/tickets/<slug>/<ticket_id>/launch")
def api_ticket_launch(slug: str, ticket_id: str):
    from ... import api_sanity
    guard = api_sanity.require_api_sanity()
    if guard is not None:
        return guard
    project, error = _project_or_404(slug)
    if error:
        return error
    ticket, error = _ticket_or_404(slug, ticket_id)
    if error:
        return error
    payload = json_body(request)
    model = payload.get("model") or ""
    # Resolve typology → profile. Relance d'un ticket EXISTANT : le caractère managé se
    # lit sur le parent DÉJÀ porté par le ticket (le manager qui l'a dispatché), pas sur
    # le payload de relance — sinon un retry manuel d'un ticket managé perdait `coder`,
    # et un retry de ticket manuel se voyait attribuer `coder` par accident.
    typology_name = payload.get("typology") or ticket.get("typology") or ""
    profile = dispatch.resolve_profile(
        typology_name, project["path"],
        managed=dispatch.is_managed_parent(ticket.get("parent", "")),
    )
    # Isolation DEMANDÉE : le payload prime, sinon celle DÉJÀ inscrite sur le ticket (un
    # ticket provisionné en worktree doit le rester à la relance), sinon 'shared'.
    # Elle passe par le MÊME garde-fou anti-collision que /api/dispatch et la création :
    # sans lui, une relance sans `isolation` repartait droit dans le dépôt principal, même
    # occupé par un agent qui y écrivait déjà — les deux s'y écrasaient en silence.
    isolation, _reason, collision_note = dispatch.resolve_isolation(
        project["path"], payload.get("isolation") or ticket.get("isolation") or dispatch.SHARED
    )
    # Retry ISOLÉ en place : re-provisionne un worktree pour ce ticket (crashé/reapé) et
    # réutilise son id au lieu de créer un doublon ; les drapeaux terminaux du run précédent
    # sont purgés pour que le ticket redevienne actif.
    cwd = project["path"]
    if isolation != dispatch.SHARED:
        # Inscrite AVANT `reisolate`, qui lit `ticket["isolation"]` pour décider du venv.
        ticket["isolation"] = isolation
        cwd = dispatch.reisolate(slug, ticket, project["path"])
        for terminal_flag in ("done", "crashed", "reaped"):
            ticket.pop(terminal_flag, None)
        tickets.update_ticket(slug, ticket)
    if collision_note:
        tickets.add_comment(slug, ticket, collision_note, True)
    try:
        agent = runner.create_agent(
            ticket["prompt"], model, cwd,
            profile=profile,
            # RATTACHER LE PARENT D'ORIGINE : sans ça, l'agent de reprise (retry d'un ticket
            # crashé/reapé) naissait ORPHELIN → invisible dans l'arbre du manager parent → son
            # digest restait figé sur l'ancien enfant crashé et il re-livrait le même verdict.
            parent=ticket.get("parent") or "",
            ticket_slug=slug, ticket_id=ticket_id,
        )
    except runner.MissingProviderEnvError as exc:
        return jsonify({"error": str(exc)}), 500
    tickets.add_run(slug, ticket, agent.agent_id, "work", model, typology=typology_name)
    return jsonify({"key": f"agent/{agent.agent_id}"})


@tickets_bp.post("/api/tickets/<slug>/<ticket_id>/validate")
def api_ticket_validate(slug: str, ticket_id: str):
    project, error = _project_or_404(slug)
    if error:
        return error
    ticket, error = _ticket_or_404(slug, ticket_id)
    if error:
        return error
    from ... import api_sanity
    refused = api_sanity.require_api_sanity()
    if refused is not None:
        return refused
    payload = json_body(request)
    model = payload.get("model") or ""
    meta = ticket.get("worktree")
    if meta and meta.get("worktree"):
        cwd = meta["worktree"]
        diff = worktrees.harvest(meta, ticket["title"]).get("diff", "")
    else:
        cwd = project["path"]
        diff = ""
    report = tickets.coder_report(ticket)
    prompt = tickets.build_validator_prompt(ticket, diff, report)
    # PARENT = l'agent CODEUR du run 'work' (id réel), pas un littéral orphelin. Même logique
    # que services/work/integration.spawn_validator : sans parent, le validateur naît orphelin
    # et remonte en fausse RACINE dans l'arbre (au lieu d'être imbriqué sous son codeur).
    work = next((r for r in ticket.get("runs") or [] if r.get("kind") == "work"), None)
    parent = work["agent_id"] if work else "dispatcher:validate"
    agent = runner.create_agent(prompt, model, cwd, profile="coder", parent=parent,
                                ticket_slug=slug, ticket_id=ticket_id, run_kind="validate")
    tickets.add_run(slug, ticket, agent.agent_id, "validate", model)
    return jsonify({"key": f"agent/{agent.agent_id}"})


@tickets_bp.post("/api/tickets/<slug>/<ticket_id>/comments")
def api_ticket_comment(slug: str, ticket_id: str):
    ticket, error = _ticket_or_404(slug, ticket_id)
    if error:
        return error
    payload = json_body(request)
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text requis"}), 400
    if payload.get("send"):
        # Même logique de continuation que /api/agent/message (source unique).
        result = messaging.send_to_ticket_agent(slug, ticket, text)
        if not result["ok"]:
            # `reason` remonte tel quel : le client doit pouvoir distinguer « l'agent
            # travaille, réessaie » d'« agent introuvable, rien n'est parti » sans lire
            # une phrase française. Sans lui, un échec définitif était rejoué en boucle.
            return jsonify({"error": result["error"],
                            "reason": result.get("reason", "")}), result.get("code", 409)
        return jsonify({"ok": True, "sent": True})
    tickets.add_comment(slug, ticket, text, False)
    return jsonify({"ok": True, "sent": False})


@tickets_bp.get("/api/tickets/<slug>/<ticket_id>/results")
def api_ticket_results(slug: str, ticket_id: str):
    project, error = _project_or_404(slug)
    if error:
        return error
    ticket, error = _ticket_or_404(slug, ticket_id)
    if error:
        return error
    return jsonify(results.ticket_results(project, ticket))


@tickets_bp.post("/api/tickets/<slug>/<ticket_id>/integrate")
def api_ticket_integrate(slug: str, ticket_id: str):
    """Intègre le worktree d'un ticket isolé dans la base (merge), ou lance un agent
    de résolution si conflit. Cleanup auto si merge propre.

    SEUL point d'entrée du merge depuis le retrait de la chaîne automatique : c'est le
    manager ou l'utilisateur qui décide qu'un travail est bon à livrer. Un ticket
    ÉPHÉMÈRE (bac à sable de test) n'est jamais mergé — on ne fauche que son worktree."""
    ticket, error = _ticket_or_404(slug, ticket_id)
    if error:
        return error
    if ticket.get("ephemeral"):
        return jsonify(integration.finalize_ephemeral(slug, ticket))
    result = integration.integrate_ticket(slug, ticket)
    return jsonify(result)


@tickets_bp.post("/api/tickets/<slug>/<ticket_id>/completed")
def api_ticket_completed(slug: str, ticket_id: str):
    """Notifié par le hook on_completion d'un agent gouverné : marque le run terminé et
    rejoue la machine à états, réduite au signalement de crash (plus AUCUNE suite
    automatique : ni test-gate, ni validateur, ni merge). L'agent qui a fini (`agent_id`)
    est traité comme terminé même si son process n'a pas encore quitté."""
    project, error = _project_or_404(slug)
    if error:
        return error
    payload = json_body(request)
    done_agent = (payload.get("agent_id") or "").strip()
    # Deferred close: the FinalAnswer queued checks (e.g. an Azure deploy) that the runner
    # drains AFTER the process exits. Advancing now would validate/merge before the deploy
    # even runs. Do nothing here — the reconciler (wake._reconcile_graceful_close) advances
    # the chain once the drain has deleted <session>.deferred.json (all checks green).
    if (payload.get("close_reason") or "") == "final_answer_deferred":
        return jsonify({"ok": True, "advanced_to": None, "deferred": True})
    # API crash: an ungraceful death (BadRequestError/APIStatusError after retries exhausted)
    # sets close_reason=api_error. NEVER advance the coder->validator->merge chain on a crash —
    # the crash is reconciled independently by wake._reconcile_api_crash (ticket -> crashed).
    if (payload.get("close_reason") or "") == "api_error":
        return jsonify({"ok": True, "advanced_to": None, "api_error": True})
    # Le hook n'avance QUE ce ticket : on ne lit et ne rafraîchit que lui. La version
    # précédente chargeait TOUS les tickets du projet (jusqu'à 6,9 Mo de JSON décodés) et
    # réécrivait leurs verdicts pour n'en faire avancer qu'un. Un ticket archivé reste hors
    # jeu (il l'était déjà : list_tickets masque les archivés par défaut).
    ticket = tickets.get_ticket(slug, ticket_id)
    if ticket is None or ticket.get("archived"):
        return jsonify({"error": f"ticket inconnu: {ticket_id}"}), 404
    tickets.refresh_verdicts(slug, [ticket], done_agent=done_agent)
    # Un run WORK clos sur text_no_tools = agent codeur arrêté EN PLEIN MILIEU (tour fini
    # sur du texte, sans tool_calls ni FinalAnswer) = AUCUNE livraison. Ne PAS le marquer
    # completed : router CRASH (comme api_error) pour que l'échec soit VISIBLE.
    # Les runs validate/manager gardent le droit de clore sur text_no_tools (verdict dans le texte).
    done_run = next((r for r in ticket.get("runs") or []
                     if isinstance(r, dict) and r.get("agent_id") == done_agent), None)
    if done_run is not None and wake._is_work_abandoned_mid_turn(
            done_run, (payload.get("close_reason") or "")):
        workflow._act_report_crash(slug, ticket, "")
        reaper.reap_ticket(slug, ticket)
        return jsonify({"ok": True, "advanced_to": "crashed", "crashed": True})
    # Marque le run comme terminé PROPREMENT avant d'avancer : le watchdog s'en sert pour
    # distinguer une clôture gracieuse (completed) d'un crash (process mort sans marqueur).
    if done_agent:
        tickets.mark_run_completed(slug, ticket, done_agent)
    next_state = workflow.advance(slug, ticket, done_agent=done_agent)
    reaper.reap_ticket(slug, ticket)  # fauche immédiatement si ce passage l'a rendu terminal
    return jsonify({"ok": True, "advanced_to": next_state})


@tickets_bp.post("/api/tickets/<slug>/<ticket_id>/done")
def api_ticket_done(slug: str, ticket_id: str):
    """Bascule `done` à la main. C'est aussi LA PORTE DE SORTIE du garde-fou de clôture
    (`closure_guard`) : cette route est déjà l'acquittement manuel d'un état que le système
    refuse de clore seul (cf. le cas `needs_attention` juste en dessous), elle est déclenchée
    par un geste humain sur le ticket exact, et le blocage y est lisible (statut « clôture
    bloquée » + commentaire nommant les enfants fautifs). Forcer ici est donc une décision
    PRISE EN CONNAISSANCE DE CAUSE, et elle est tracée comme telle."""
    ticket, error = _ticket_or_404(slug, ticket_id)
    if error:
        return error
    ticket["done"] = not ticket.get("done", False)
    forced = closure_guard.force_closure(slug, ticket) if ticket["done"] else ""
    # Acquittement manuel d'un merge bloqué : marquer done à la main un ticket needs_attention
    # est une décision explicite de résolution. Sans ça, derive_status le laisserait « merge
    # bloqué » à vie (le statut prime sur done) — on nettoie l'état worktree pour l'acter.
    meta = ticket.get("worktree")
    if ticket["done"] and isinstance(meta, dict) and meta.get("state") == "needs_attention":
        meta["state"] = "cleaned"
        meta["resolved_by"] = "manual-done"
    tickets.update_ticket(slug, ticket)
    return jsonify({"done": ticket["done"], "closure_forced": forced})


@tickets_bp.post("/api/tickets/<slug>/<ticket_id>/archive")
def api_ticket_archive(slug: str, ticket_id: str):
    """Archivage MANUEL (demandé par le user) et RÉVERSIBLE d'un ticket : il quitte le board
    actif mais reste dans le store (jamais supprimé). Seule voie de retrait volontaire.
    Réversible via .../unarchive."""
    ticket = tickets.archive_ticket(slug, ticket_id)
    if ticket is None:
        return jsonify({"error": f"ticket inconnu: {ticket_id}"}), 404
    # Archivage = décision explicite du user → on réclame le worktree (disque), branche gardée.
    # C'est, avec le merge, la seule voie qui retire le worktree d'un crashed/failed reprenable.
    reaped = reaper.reap_archived(slug, ticket)
    return jsonify({"ok": True, "id": ticket_id, "archived": True, "worktree_reaped": reaped})


@tickets_bp.post("/api/tickets/<slug>/<ticket_id>/unarchive")
def api_ticket_unarchive(slug: str, ticket_id: str):
    """Restaure un ticket archivé sur le board actif."""
    ticket = tickets.unarchive_ticket(slug, ticket_id)
    if ticket is None:
        return jsonify({"error": f"ticket inconnu: {ticket_id}"}), 404
    return jsonify({"ok": True, "id": ticket_id, "archived": False})
