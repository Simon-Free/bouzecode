# [desc] Agents, vue transverse (spec §6.4) : GET /api/agents (pur, paginé, filtres), fiche, enfants (404 si inconnu), conversation libre (POST /api/agents) et gestes sur un agent par son id (messages, stop, interruptions). [/desc]
from __future__ import annotations

from flask import Blueprint, request

from ...schema import corps_attendu
from ...runtime.runner import agent_commande, agent_creation
from ...services import file_service
from ...services.work.api_tickets import agents_vue, controle, garde, remise
from ...services.work.api_tickets.refus import Refus
from ._commun import corps, json

agents_api_bp = Blueprint("agents_v3_api", __name__)

_MODES = {"queue": remise.FILE, "now": remise.INTERROMPRE, "refuse": remise.REFUSER}


@agents_api_bp.get("/api/agents")
def api_agents_lister():
    """?state=&parent=&project=&limit=&cursor= → {agents:[{agent_id, key, title, state, parent,
    project_slug, ticket_id, ticket_state…}], next_cursor, total}. `state` accepte aussi
    `awaiting_input` (avec la question), `unreachable`, `interrupted` (+ le rapport du démarrage : `boot_at`, `items`),
    `stopped`. LECTURE PURE."""
    a = request.args
    return json(agents_vue.lister(a.get("state") or "", a.get("parent") or "",
                                  a.get("project") or "", a.get("limit"), a.get("cursor")))


@agents_api_bp.post("/api/agents")
@corps_attendu(prompt="texte, requis", model="modèle", cwd="dossier de travail",
               typology="typologie", parent="agent parent")
def api_agents_conversation():
    """{prompt, model?, cwd?, typology?} → 201 {key, agent_id} : conversation LIBRE hors projet
    (pour travailler sur un projet, créer un ticket). 503 `env_indisponible`."""
    from ...services.typologies import get_typology
    payload = corps()
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise Refus("prompt_requis", "prompt requis", 400)
    garde.exiger()
    cwd = payload.get("cwd") or str(file_service.ROOT)
    typologie = get_typology(payload["typology"], cwd) if payload.get("typology") else None
    try:
        agent = agent_creation.create_agent(prompt, payload.get("model") or "", cwd,
                                    profile=typologie["profile"] if typologie else "",
                                    parent=payload.get("parent") or "")
    except agent_commande.MissingProviderEnvError as exc:
        raise Refus("provider_absent", str(exc), 503) from exc
    return json({"key": f"agent/{agent.agent_id}", "agent_id": agent.agent_id}, 201)


@agents_api_bp.get("/api/agents/<agent_id>")
def api_agent_fiche(agent_id: str):
    """La fiche d'un agent : état, ticket (état projeté), run, parent, enfants. 404."""
    return json(agents_vue.fiche(agent_id))


@agents_api_bp.get("/api/agents/<agent_id>/children")
def api_agent_enfants_v3(agent_id: str):
    """{agent_id, children:[…]} : ses enfants (tickets dont il est le parent), lus FRAIS dans
    le store. 404 `agent_inconnu` si rien ne le connaît."""
    return json(agents_vue.enfants_de(agent_id))


@agents_api_bp.post("/api/agents/<agent_id>/messages")
@corps_attendu(text="texte (vide = reprendre)", mode="queue (défaut) | now | refuse",
               commenter="booléen, défaut true")
def api_agent_message_v3(agent_id: str):
    """{text, mode?: queue|now|refuse} → 200 {delivered} | 202 {queued, queue_id, position} :
    la remise UNIQUE d'un message (même service que …/tickets/{id}/messages). `text` vide =
    « reprendre ». 404 `agent_missing`, 409 `running` (mode refuse) / `not_delivered`."""
    payload = corps()
    mode = str(payload.get("mode") or "queue")
    if mode not in _MODES:
        raise Refus("mode_inconnu", f"mode inconnu : {mode!r} (queue, now ou refuse)", 400)
    rendu = remise.remettre(remise.agent_ou_refus(agent_id), str(payload.get("text") or "").strip(),
                            _MODES[mode], commenter=bool(payload.get("commenter", True)))
    return json(rendu, 202 if rendu.get("queued") else 200)


@agents_api_bp.post("/api/agents/<agent_id>/stop")
def api_agent_arreter(agent_id: str):
    """→ 202 {ok} : arrête le process de l'agent (estampillé, demande d'arrêt journalisée sur
    son ticket : plus de réveil automatique). 404 `agent_missing`, 502 `arret_refuse`."""
    return json(controle.arreter_agent(remise.agent_ou_refus(agent_id)), 202)


@agents_api_bp.post("/api/agents/<agent_id>/question/archive")
def api_agent_question_archive(agent_id: str):
    """→ 200 {ok, archived} : classe SANS réponse la question d'un agent ARRÊTÉ (corps
    optionnel {comment}). Elle sort de « À traiter » ; une nouvelle question réapparaît.
    404 `agent_missing` / `not_waiting`, 409 `agent_alive` (l'agent vit : réponds-lui)."""
    from ...services.work import awaiting
    remise.agent_ou_refus(agent_id)
    body = request.get_json(silent=True) or {}
    comment = str(body.get("comment") or "").strip()
    return json({"ok": True, "archived": awaiting.archive_stopped_question(agent_id, comment)})


@agents_api_bp.post("/api/agents/<agent_id>/interruptions")
def api_agent_interruption(agent_id: str):
    """→ 202 {ok, escalated} : interruption DOUCE du tour (cancel.flag), escalade en kill si
    l'agent ne cède pas en ~1,5 s ; il reste reprenable. 404 `agent_missing`, 502 `arret_refuse`."""
    return json(controle.interrompre_agent(remise.agent_ou_refus(agent_id)), 202)
