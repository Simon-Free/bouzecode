# [desc] Gestes sur l'agent d'un ticket (spec §6.3) : POST runs (202, 409 deja_actif), messages (200 delivered / 202 queued / 409 pas_d_agent), answer, interrupt (202), stop (202, 502 arret_refuse). [/desc]
from __future__ import annotations

from flask import Blueprint

from ...schema import corps_attendu
from ...services.work import tickets
from ...services.work.api_tickets import controle, lancement, remise
from ...services.work.api_tickets.refus import Refus
from ._commun import corps, json, ticket_ou_refus

gestes_bp = Blueprint("tickets_gestes_api", __name__)

_MODES = {"queue": remise.FILE, "now": remise.INTERROMPRE}


@gestes_bp.post("/api/projects/<slug>/tickets/<ticket_id>/runs")
@corps_attendu(profile="profil", model="modèle", prompt_suffix="texte ajouté au prompt",
               kind="work (défaut) | merge_fix")
def api_ticket_lancer(slug: str, ticket_id: str):
    """{profile?, model?, prompt_suffix?, kind?} → 202 {run, ticket, launch_key} : un agent NEUF
    (relance ; `merge_fix` sur un conflit), avec l'isolation DU TICKET. 409 `deja_actif`,
    `transition_refusee`, `archive`, `collision_isolation` ; 503 `env_indisponible`."""
    ticket_ou_refus(slug, ticket_id, geste=True)
    return json(lancement.lancer(slug, ticket_id, corps()), 202)


@gestes_bp.post("/api/projects/<slug>/tickets/<ticket_id>/messages")
@corps_attendu(text="texte, requis", mode="queue (défaut) | now (coupe le tour)",
               arreter="booléen : demande d'arrêt du parent", origine="parent | vide")
def api_ticket_message(slug: str, ticket_id: str):
    """{text, mode?: queue|now} → 200 {delivered: true} (agent au repos, relancé avec le
    message) | 202 {queued: true, queue_id, position} (agent en plein tour ; `now` coupe le
    tour). 409 `pas_d_agent` (aucun run : POST …/runs), 404 `agent_missing` ; un message non
    remis est gardé au journal comme commentaire NON envoyé (`commentaire_conserve`)."""
    ticket = ticket_ou_refus(slug, ticket_id, geste=True)
    payload = corps()
    texte = str(payload.get("text") or "").strip()
    if not texte:
        raise Refus("texte_requis", "text requis", 400)
    mode = str(payload.get("mode") or "queue")
    if mode not in _MODES:
        raise Refus("mode_inconnu", f"mode inconnu : {mode!r} (queue ou now)", 400)
    try:
        rendu = remise.remettre(remise.agent_du_ticket(ticket), texte, _MODES[mode],
                                origine=str(payload.get("origine") or ""),
                                arreter=bool(payload.get("arreter")), du_ticket=(slug, ticket))
    except Refus as refus:  # jamais perdu (C7) : le texte reste au journal, NON envoyé
        tickets.add_comment(slug, ticket, texte, False)
        refus.details["commentaire_conserve"] = True
        raise
    return json(rendu, 202 if rendu.get("queued") else 200)


@gestes_bp.post("/api/projects/<slug>/tickets/<ticket_id>/answer")
@corps_attendu(question_id="id de la question", choice="option choisie", text="réponse libre")
def api_ticket_repondre(slug: str, ticket_id: str):
    """{question_id?, choice?, text?} → 200 : réponse à la question en attente
    (awaiting_input → running). 409 `pas_de_question`."""
    ticket = ticket_ou_refus(slug, ticket_id, geste=True)
    payload = corps()
    return json(controle.repondre(ticket, str(payload.get("question_id") or ""),
                                  str(payload.get("choice") or ""), str(payload.get("text") or "")))


@gestes_bp.post("/api/projects/<slug>/tickets/<ticket_id>/interrupt")
def api_ticket_interrompre(slug: str, ticket_id: str):
    """→ 202 {ok, escalated} : annule doucement le tour en cours (escalade en kill si l'agent ne
    cède pas) ; l'agent reste reprenable. 409 `pas_d_agent`, 502 `arret_refuse`."""
    return json(controle.interrompre_ticket(slug, ticket_ou_refus(slug, ticket_id)), 202)


@gestes_bp.post("/api/projects/<slug>/tickets/<ticket_id>/stop")
def api_ticket_arreter(slug: str, ticket_id: str):
    """→ 202 {ok, state} : arrête le lancement ou l'agent (ticket `stopped`). Idempotent ; 502
    `arret_refuse` si l'OS refuse."""
    return json(controle.arreter_ticket(slug, ticket_ou_refus(slug, ticket_id)), 202)
