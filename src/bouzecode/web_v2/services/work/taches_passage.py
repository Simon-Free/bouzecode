# [desc] Un PASSAGE de tâche du Bureau (un ticket lancé depuis elle) : son état est la projection de `ticket.state` dans le lexique des agents, jamais une redérivation. [/desc]
"""Extrait de `taches_vue.py`. Le Bureau est un CLIENT du backend des tickets (spec §2) : l'état
d'un passage se lit sur `ticket.state` (+ `state_reason`). L'agent n'est consulté que pour ce
que l'état ne dit pas : la phase d'un agent qui tourne (« le modèle lit ta demande… »), le
texte de sa question, son récap, son activité, sa joignabilité."""
from __future__ import annotations

from pathlib import Path

from . import lexique
from .etat_ticket import code_raison, vue_rattachee
from .fsm import etats

#: ticket.state → clé du lexique d'un agent (`lexique.LEXIQUE`).
_ETAT_DU_PASSAGE = {
    etats.CREATED: "crashed", etats.PROVISIONING: "preparing",
    etats.LAUNCH_FAILED: "launch_failed", etats.RUNNING: "running",
    etats.AWAITING_INPUT: "awaiting_input", etats.DELIVERED: "finished",
    etats.IDLE_NO_DELIVERY: "crashed", etats.STOPPED: "crashed",
    etats.INTEGRATING: "finished", etats.CONFLICT: "finished",
    etats.CLOSED: "finished", etats.ABANDONED: "finished",
}
_ARRETS_DEMANDES = ("interrupted", "killed", "arret_preparation")


def etat_du_passage(ticket: dict, statut: dict | None) -> str:
    """La clé du lexique d'un passage : projection de `state`, précisée par la raison (manager
    garé, agent introuvable) et, pour un agent qui tourne, par sa phase vivante."""
    state, code, statut = ticket.get("state"), code_raison(ticket), statut or {}
    if state == etats.RUNNING:
        if code == "attend_enfants":
            return "orchestrating"
        return lexique.etat_agent("running", "", str(statut.get("phase") or ""))
    if state == etats.AWAITING_INPUT:
        live = str(statut.get("state") or "")
        return live if live in lexique.ETATS_ATTENTE else "awaiting_input"
    if state == etats.STOPPED and code == "introuvable":
        return "missing"
    return _ETAT_DU_PASSAGE.get(str(state), "missing")


def raison_d_echec(ticket: dict, agent) -> str:
    """Pourquoi le passage n'a pas fini — lu sur `state_reason`, jamais deviné."""
    raison = ticket.get("state_reason") or {}
    code, message = str(raison.get("code") or ""), str(raison.get("message") or "")
    if ticket.get("state") == etats.LAUNCH_FAILED:
        return f"Lancement échoué : {message or 'erreur inconnue'}"
    if ticket.get("state") == etats.CREATED:
        return "Aucun agent n'a démarré pour ce passage"
    if code in _ARRETS_DEMANDES:
        return lexique.RAISON_ARRET_DEMANDE
    constat = str(getattr(agent, "fin_constatee", "") or "") or message
    if ticket.get("state") == etats.IDLE_NO_DELIVERY:
        return f"L'agent s'est arrêté sans réponse finale ({code or 'fin forcée'})"
    return f"L'agent s'est arrêté sans réponse finale : {constat}" if constat \
        else "L'agent s'est arrêté sans réponse finale"


def _worktree(ticket: dict) -> tuple[str, bool | None]:
    from .etat_ticket import integre
    meta = ticket.get("worktree")
    if not isinstance(meta, dict) or not meta:
        return "", None
    branche = str(meta.get("branch") or "")
    if integre(ticket):
        return branche, True
    return branche, (False if meta.get("worktree") else None)


def vue_vide(numero: int, slug: str, ticket_id: str, lien_at: str) -> dict:
    return {"numero": numero, "slug": slug, "ticket_id": ticket_id, "agent_id": "", "key": "",
            "etat": "missing", "libelle_etat": "", "started_at": lien_at, "finished_at": "",
            "activite": "", "recap": {"fait": [], "reste": [], "a_decider": [], "resume": ""},
            "rapport_html": "", "fichiers_modifies": None, "branche": "", "integre": None,
            "integrable": False, "joignable": False, "vivant": False, "retour": "",
            "retours_envoyes": [], "raison_echec": "", "question": None}


def appliquer_retours(vue: dict, retours: list[dict]) -> None:
    """Le retour qui a OUVERT ce passage, et ceux envoyés ensuite à son agent (« continuer »)."""
    for retour in retours:
        if retour.get("mode") == "continuer":
            vue["retours_envoyes"].append(retour["texte"])
        elif not vue["retour"]:
            vue["retour"] = retour["texte"]


def _joignable(agent, etat: str) -> bool:
    """Une conversation reprenable : un état connu et une session sur disque."""
    if agent is None or etat in ("missing", "launch_failed", "preparing"):
        return False
    chemin = getattr(agent, "session_path", "") or ""
    return bool(chemin and Path(chemin).exists())


def _avec_agent(vue: dict, ctx, ticket: dict, agent) -> None:
    from bouzecode.web_v2.runtime.runner import agent_vivacite

    from . import activity
    from .taches_vue import recap_d_agent
    statut = ctx.statut(agent)
    vue.update(etat=etat_du_passage(ticket, statut),
               finished_at=str(getattr(agent, "finished_at", "") or ""),
               vivant=bool(agent_vivacite.is_running(agent)))
    if vue["etat"] in lexique.ETATS_ATTENTE:
        vue["question"] = {"texte": statut.get("question", ""),
                           "options": statut.get("options") or [],
                           "allow_freetext": bool(statut.get("allow_freetext", True)),
                           "agent_id": agent.agent_id}
    if vue["etat"] in lexique.ETATS_ACTIFS:
        vue["activite"] = (activity.describe(statut, {}) or {}).get("activity_label", "")
    else:
        recap = recap_d_agent(agent)
        if recap:
            vue["recap"] = {k: recap[k] for k in ("fait", "reste", "a_decider", "resume")}
            vue["fichiers_modifies"] = recap.get("fichiers")
            vue["rapport_html"] = recap.get("rapport_html") or ""


def _avec_humain(vue: dict, ticket: dict, travail: dict) -> None:
    """Passage RENDU par un humain : même récap que celui d'un agent, lu dans la
    session synthétique (dernier appel FinalAnswer) écrite par `rendu_humain`."""
    from pathlib import Path

    from .taches_vue import _recap_lu
    vue.update(etat=etat_du_passage(ticket, None), auteur=str(travail.get("auteur") or ""),
               humain=True, commits=list(travail.get("commits") or []))
    chemin = str(travail.get("session_path") or "")
    recap = _recap_lu(Path(chemin)) if chemin and Path(chemin).is_file() else None
    if recap:
        vue["recap"] = {k: recap.get(k) for k in ("fait", "reste", "a_decider", "resume")}
        vue["fichiers_modifies"] = recap.get("fichiers")
        vue["rapport_html"] = recap.get("rapport_html") or ""


def _sans_agent(vue: dict, ticket: dict, ticket_id: str) -> None:
    from . import launch_phase
    vue["etat"] = etat_du_passage(ticket, None)
    if vue["etat"] == "preparing":
        phase = launch_phase.phase_view(ticket)
        texte = phase.get("phase_label") or "Préparation de l'environnement"
        if phase.get("phase_detail"):
            texte += f" — {phase['phase_detail']}"
        vue.update(activite=texte, launch_key=f"launching/{ticket_id}")


def _vue_distante(ticket: dict, run: dict) -> dict:
    """L'exécution Rundeck d'un passage, pour la carte : lien, mode, fichiers NON transmis."""
    lancement = ticket.get("distant") if isinstance(ticket.get("distant"), dict) else {}
    refuses = {slug: liste for slug, liste in (lancement.get("fichiers_refuses") or {}).items()
               if liste}
    return {"execution_id": str(run.get("execution_id") or ""), "url": str(run.get("url") or ""),
            "mode": str(run.get("mode") or "agent"), "fichiers_refuses": refuses}


def passage(ctx, slug: str, ticket_id: str, lien_at: str, numero: int) -> dict:
    """Un passage = un ticket lancé depuis la tâche, vu par SON état (`ticket.state`)."""
    vue = vue_vide(numero, slug, ticket_id, lien_at)
    appliquer_retours(vue, ctx.retours_du_ticket.get(ticket_id, []))
    trouve = ctx.tickets.get(ticket_id)
    if trouve is None:
        vue.update(raison_echec="Ticket introuvable (supprimé du store)",
                   libelle_etat=lexique.libelle_etat("missing"))
        return vue
    vue["slug"], ticket = trouve
    vue["branche"], vue["integre"] = _worktree(ticket)
    travail = next((r for r in ticket.get("runs") or [] if isinstance(r, dict)
                    and r.get("kind") in ("work", "merge_fix", "remote", "humain")), None)
    agent = None
    if travail is not None:
        agent_id = str(travail.get("agent_id") or "")
        vue.update(agent_id=agent_id, started_at=str(travail.get("started_at") or lien_at),
                   key=f"agent/{agent_id}" if agent_id
                   and travail.get("kind") not in ("remote", "humain") else "")
        agent = ctx.agents.get(agent_id)
    if travail is not None and travail.get("kind") == "remote":
        from .distant import runs as runs_distants  # exécution Rundeck : aucune fiche d'agent
        vue.update(runs_distants.vue_passage(travail, lien_at), etat=etat_du_passage(ticket, None))
        vue["distant"] = _vue_distante(ticket, travail)
    elif travail is not None and travail.get("kind") == "humain":
        _avec_humain(vue, ticket, travail)
    elif agent is not None:
        _avec_agent(vue, ctx, ticket, agent)
    else:
        _sans_agent(vue, ticket, ticket_id)
    if vue["etat"] in ("crashed", "launch_failed", "missing") and not vue["raison_echec"]:
        vue["raison_echec"] = (raison_d_echec(ticket, agent) if vue["etat"] != "missing"
                               or ticket.get("state") == etats.STOPPED
                               else "Fiche de l'agent introuvable")
    vue["libelle_etat"] = lexique.libelle_etat(vue["etat"])
    vue["joignable"] = _joignable(agent, vue["etat"])
    vue["integrable"] = vue["integre"] is False and vue["etat"] not in lexique.ETATS_ACTIFS
    vue.update(vue_rattachee(ticket))
    return vue
