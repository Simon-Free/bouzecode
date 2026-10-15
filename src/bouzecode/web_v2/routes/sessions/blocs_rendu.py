# [desc] Rendu des blocs du fil : bloc texte (plain), blocs HTML numérotés par tour, marqueurs de sous-agents intercalés, statut avec vivacité et état du ticket, conversation encore en lancement. [/desc]
from __future__ import annotations

from flask import jsonify

from ...runtime.runner import agent_registre
from ...services import message_view
from ...services.erreurs import Refus
from ...services.sessions import blocs_rendus, store
from ...services.work import launch_phase, liveness

LAUNCHING_PREFIX = "launching/"


def bloc_texte(index: int, message: dict) -> dict:
    name = message.get("name", "")
    text = message_view._content_text(message)[:8000]
    kind = message_view._final_answer_kind(str(name), text)
    block: dict = {"idx": index, "role": message.get("role", ""), "name": name, "text": text,
                   "tool_calls": [{"name": tc.get("name"), "input": tc.get("input")}
                                  for tc in message.get("tool_calls") or []]}
    if kind:
        block["kind"] = kind
    return block


def statut_avec_vivacite(agent) -> dict:
    """Statut de session SERVI au front, enrichi de la VIVACITÉ dérivée de preuves (la MÊME que
    `/api/agents/tree` et la liste de tickets, `liveness.classify_agent`) et de l'état du TICKET
    (`ticket_state`, `libelle_ticket`…) : le front n'a AUCUNE règle à redériver. `interrupted`
    (bouton « décider de son sort ») est exactement « mort sans clôture prouvée »."""
    if agent is None:
        return {"state": "cli"}
    live = liveness.classify_agent(agent)
    return {**store.agent_status(agent), "liveness": live, "interrupted": live == "crashed",
            **_etat_du_ticket(agent)}


def _etat_du_ticket(agent) -> dict:
    from ...services.work import tickets
    from ...services.work.etat_ticket import vue_rattachee
    slug, ticket_id = getattr(agent, "ticket_slug", ""), getattr(agent, "ticket_id", "")
    return vue_rattachee(tickets.get_ticket(slug, ticket_id)) if slug and ticket_id else {}


def _ticket_par_id(ticket_id: str) -> dict:
    """Le ticket, cherché dans TOUS les stores (un dépôt retiré entre-temps compte aussi)."""
    from ...services.work import _persistence
    return next((t for _, t in _persistence.all_tickets() if str(t.get("id")) == ticket_id), None) or {}


def _agent_ne_de(ticket_id: str, ticket: dict) -> str:
    """L'agent né du lancement : le run posé au spawn d'abord (ne dépend pas du cache du parc,
    qui ignore un agent né il y a moins d'une seconde), le parc sinon."""
    runs = [r for r in (ticket.get("runs") or []) if r.get("agent_id")]
    if runs:
        return runs[-1]["agent_id"]
    return next((a.agent_id for a in agent_registre.list_agents()
                 if (getattr(a, "ticket_id", "") or "") == ticket_id), "")


def blocs_de_lancement(ticket_id: str):
    """`/blocks` d'une conversation en provisionnement (clé `launching/<id>`) : l'étape en cours
    (worktree, uv sync, spawn) ; une fois le lancement fini, l'agent né (200 + `agent_key`), le
    lancement échoué (200 + `launch_failed`), ou 404 `lancement_inconnu`."""
    status = launch_phase.status_for(ticket_id)
    if status is not None:
        return jsonify({"total": 0, "blocks": [], "status": status, "meta": {}})
    ticket = _ticket_par_id(ticket_id)
    born_id = _agent_ne_de(ticket_id, ticket)
    if born_id:
        return jsonify({"total": 0, "blocks": [], "meta": {}, "agent_key": f"agent/{born_id}",
                        "status": {"state": "starting"}})
    if ticket.get("state") == "launch_failed":
        raison = ticket.get("state_reason") or {}
        return jsonify({"total": 0, "blocks": [], "meta": {}, "status": {"state": "launch_failed"},
                        "launch_failed": True,
                        "launch_error": str(raison.get("message") or "le lancement a échoué")})
    raise Refus("lancement_inconnu", f"aucun lancement en cours : {ticket_id}", 404,
                ticket_id=ticket_id)


def blocs_html(key: str, path, messages: list, plage: tuple[int, int], events: list | None) -> list:
    """Les blocs HTML de la plage ; chaque message assistant porte le lien du diagnostic de SON
    tour (numéroté depuis le début du fil : stable en polling incrémental). Les marqueurs
    « N agent(s) lancé(s) » ne sont intercalés qu'au chargement initial (ou d'une page plus
    ancienne) : ils n'entrent pas dans `total`."""
    tours: dict[int, int] = {}
    for j, message in enumerate(messages):
        if message.get("role") == "assistant":
            tours[j] = len(tours) + 1
    blocks = [{"idx": i, "html": blocs_rendus.rendre(
        str(path), i, messages[i],
        f"/api/sessions/{key}/turns/{tours[i]}/context" if i in tours else None)}
        for i in range(*plage)]
    return _intercaler_les_sous_agents(blocks, messages, events, plage) if events else blocks


def _vagues_de_lancement(events: list[dict]) -> list[list[dict]]:
    """Un `launch` ouvre une vague ; les `done` qui suivent s'y rattachent."""
    waves: list[list[dict]] = []
    for ev in events:
        if ev["subtype"] == "launch" or not waves:
            waves.append([ev])
        else:
            waves[-1].append(ev)
    return waves


def _livraisons(messages: list) -> list[int]:
    """Indices des messages outil FinalAnswer (livraisons du codeur), dans l'ordre du fil."""
    return [i for i, m in enumerate(messages)
            if m.get("role") == "tool" and message_view._final_answer_kind(
                str(m.get("name", "")), message_view._content_text(m)) == "final_answer"]


def _intercaler_les_sous_agents(blocks: list, messages: list, events: list,
                                plage: tuple[int, int]) -> list:
    """La kème vague de lancement suit la kème livraison, à défaut la fin du fil. Seules les
    vagues ancrées dans la `plage` servie sont intercalées (une page plus ancienne portera les
    siennes)."""
    deliveries = _livraisons(messages)
    inserts: dict[int, list[dict]] = {}
    for k, wave in enumerate(_vagues_de_lancement(events)):
        anchor = deliveries[k] if k < len(deliveries) else len(messages) - 1
        if plage == (0, len(messages)) or plage[0] <= anchor < plage[1]:
            inserts.setdefault(anchor, []).extend(wave)

    def rendus(anchor: int) -> list[dict]:
        return [{"idx": anchor, "html": message_view.render_message(ev)}
                for ev in inserts.pop(anchor, [])]

    result: list = []
    for block in blocks:
        result.append(block)
        result.extend(rendus(block["idx"]))
    for anchor in list(inserts):  # ancres hors des blocs rendus : en fin de fil
        result.extend(rendus(anchor))
    return result


def code_perime(data: dict) -> dict:
    """Agent démarré sur un commit antérieur au HEAD du dépôt : il exécute l'ancien code."""
    from ... import version as _version
    return _version.code_staleness(data.get("bouzecode_boot_commit") or "")
