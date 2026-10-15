# [desc] Outils qui suivent ou ré-instruisent les enfants déjà lancés : MessageAgent, SendMessage, CheckAgentResult (attente, arrêt), ListAgentTasks. [/desc]
"""Les enfants d'un agent après leur lancement : les lire (`enfants.lire`), les attendre, les
arrêter, leur écrire."""
from __future__ import annotations


def _message_agent(params: dict, config: dict) -> str:
    """Ré-instruit un agent enfant DÉJÀ lancé (même agent, contexte gardé), identifié par son
    ticket_id. En mode bouzeui web : POST /api/projects/{slug}/tickets/{id}/messages (le slug
    est lu dans mes enfants). Hors web : pas de flotte de tickets gouvernés → message clair."""
    from ..tools.interaction import is_web_ipc_active
    if not is_web_ipc_active() and config.get("_tui_agents") is not None:
        from .en_process.outil import message_tui  # sous-agents du TUI, en process
        return message_tui(params, config)
    if not is_web_ipc_active():
        return ("MessageAgent n'est disponible qu'en mode bouzeui web (il ré-instruit un "
                "ticket enfant gouverné). Hors web, il n'y a pas de flotte à contacter.")
    from ..core.local_http import LocalServerError
    from .client_tickets import message_a_l_enfant
    from .enfants import mon_id

    ticket_id = params["ticket_id"]
    try:
        result = message_a_l_enfant(mon_id(config), ticket_id, params["text"],
                                    bool(params.get("interrompre", False)),
                                    bool(params.get("arreter", False)),
                                    config.get("_web_children"))
    except LocalServerError as exc:
        # `local_http` a déjà extrait le motif serveur, et nomme le proxy si la requête n'a
        # jamais atteint bouzecode.
        return f"Message NON transmis au ticket {ticket_id} : {exc}"
    if result.get("queued"):
        quand = ("son tour en cours a été coupé : il repart aussitôt avec"
                 if params.get("interrompre") else "il le lira à sa prochaine étape")
        return f"Message transmis au ticket {ticket_id} pendant qu'il travaille : {quand}."
    if result.get("ok"):
        return f"Message transmis au ticket {ticket_id}."
    return f"Message NON transmis au ticket {ticket_id} : {result.get('error', 'erreur inconnue')}"


def _send_message(params: dict, config: dict) -> str:
    from .gestionnaire import get_agent_manager
    mgr = get_agent_manager()
    target = params["to"]
    message = params["message"]
    ok = mgr.send_message(target, message)
    if ok:
        return f"Message queued for agent '{target}'. It will be processed after current work completes."
    task_id = mgr._by_name.get(target, target)
    task = mgr.tasks.get(task_id)
    if task is None:
        return f"Error: no agent found with id or name '{target}'"
    return f"Error: agent '{target}' is not running (status: {task.status}). Cannot send message."


def _check_agent_result(params: dict, config: dict) -> str:
    """État d'UN enfant : sous-agent en process, ou ticket web (par ticket_id ou agent_id).
    `wait=true` bloque jusqu'à ce qu'il rende la main — c'est « l'attendre »."""
    from . import enfants
    task_id = str(params.get("task_id") or "").strip()
    fiches, erreur = enfants.lire(config)
    fiche = next((f for f in fiches if task_id in (f.get("ticket_id"), f.get("agent_id"))), None)
    if fiche is None:
        detail = f" (enfants du serveur illisibles : {erreur})" if erreur else ""
        return f"Error: aucun de tes enfants n'a l'id '{task_id}'{detail}. Voir ListAgentTasks."
    if params.get("arreter") and fiche.get("actif"):
        return _arreter_enfant(fiche)
    if params.get("wait") and fiche.get("actif"):
        return (f"{enfants.ligne(fiche)}\nAttendu jusqu'à sa fin :\n"
                f"{enfants.attendre(fiche, config)}")
    return "\n".join([enfants.ligne(fiche), *_details_enfant(fiche)])


def _arreter_enfant(fiche: dict) -> str:
    """Arrête un enfant LOCAL : fenêtre de terminal (par son PID) ou thread en process."""
    from .gestionnaire import get_agent_manager
    if not fiche.get("local"):
        return f"Enfant web : arrête-le avec Fleet(action='kill', agent_id='{fiche.get('agent_id')}')."
    task = get_agent_manager().tasks[fiche["ticket_id"]]
    if task.result_file:
        from .surveillance_terminal import arreter
        return arreter(task)
    get_agent_manager().cancel(task.id)
    return f"{task.id} : arrêt demandé (il s'arrête à sa prochaine étape)."


def _details_enfant(fiche: dict) -> list[str]:
    """Ce qu'on sait de plus sur un enfant : son résultat (en process) ou son issue (ticket),
    et, s'il travaille encore, comment l'attendre ou l'arrêter."""
    from . import enfants
    from .gestionnaire import get_agent_manager
    details = []
    task = get_agent_manager().tasks.get(fiche["ticket_id"]) if fiche.get("local") else None
    if task is not None and task.result:
        details.append(f"\nResult:\n{task.result}")
    elif fiche.get("issue"):
        details.append(f"Issue : {fiche['issue']}")
    if fiche.get("actif"):
        details.append(f"Toujours actif : {enfants.comment_faire(fiche)}.")
    return details


def _list_agent_tasks(params: dict, config: dict) -> str:
    """Mes enfants, tels que le SERVEUR les voit (tickets web, lus frais) + mes sous-agents en
    process. Essai 3 (2026-09-24) : l'ancienne lecture passait par l'arbre servi depuis un
    cache ; un enfant né après son dernier calcul y manquait → « No sub-agent tasks » alors
    qu'il tournait, et la racine a refait son travail."""
    from . import enfants
    fiches, erreur = enfants.lire(config)
    lignes = [enfants.ligne(f) for f in fiches]
    if erreur:
        lignes.append(f"⚠ enfants lancés via le serveur ILLISIBLES ({erreur}) : cette liste est "
                      "incomplète, n'en conclus PAS qu'un enfant a disparu.")
    if not lignes:
        return "No sub-agent tasks."
    return "\n".join(["Tes enfants — tous lancés par toi (outil Agent) :",
                      "ticket | lancement | agent | état | branche | worktree | objectif",
                      *lignes])
