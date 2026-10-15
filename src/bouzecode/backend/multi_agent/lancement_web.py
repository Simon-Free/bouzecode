# [desc] Chemin web de l'outil Agent : crée le ticket gouverné de l'enfant via le serveur, rend les refus comme erreurs d'outil, puis attend son verdict ou rend la main. [/desc]
"""`Agent` sous bouzeui web (IPC web active) : un enfant = un ticket gouverné."""
from __future__ import annotations

import os

from .appel_agent import _attend_l_enfant
from .attente_web import _attente_de_mes_enfants, _wait_for_child
from .travail_non_commite import _avertir_travail_non_commite


def _default_web_dispatch(body: dict) -> dict:
    """Crée le ticket de l'enfant par LA route de création (`POST /api/projects/{slug}/tickets`,
    `client_tickets.creer_ticket`) — écrivain unique, jamais proxyfié (`core.local_http`, panne
    407 du 2026-07-28). Timeout large : 180 s couvre la création sans faux timeout (doublon)."""
    from .client_tickets import creer_ticket
    return creer_ticket(body)


def _spawn_web_ticket_agent(params: dict, config: dict) -> str:
    """Sous-agent en mode bouzeui web = TOOL CALL LONG à 2 modes (PAS une fin de tour).

    Crée un TICKET gouverné via le serveur (écrivain unique → pas de race) et attache
    parent=<self> pour être ré-invoqué automatiquement quand l'enfant aura fini
    (cf. web_v2.services.work.wake).

    Modes (le défaut est la PAUSE — cf. `_attend_l_enfant`) :
      - background=True : dispatch le ticket, RÉ-INVITE le manager à continuer son tour
        (lancer d'autres Agent, poursuivre son travail). Pose
        config["_bg_agent_launched"]=True pour que le turn-protocol NE nudge PAS vers
        FinalAnswer ce tour-ci tant qu'un Agent lancé maintenant tourne.
      - défaut (ni `background` ni `wait`) ou wait=True : bloque jusqu'au verdict de
        l'enfant et le renvoie.
    Dans les DEUX modes, N appels Agent d'un même message partent ENSEMBLE : le dispatcher
    DAG les lance comme un lot simultané (`ToolDef.lot_simultane`). Avant, il les rangeait
    dans sa file séquentielle et un lot en mode pause attendait l'enfant 1 avant de LANCER
    l'enfant 2 (mesuré le 2026-09-25 : 4 dispatchs à 14:59, 15:11, 15:17, 15:27).

    Dépendances injectables (testabilité sans mock.patch) :
      - config["_web_dispatch"](body:dict)->dict  (défaut = POST urllib réel)
      - config["_web_wait_verdict"](ticket_id:str, project_slug:str)->str
        (défaut = poll urllib réel ; le slug est REQUIS, la route ticket en a besoin)
    """
    from pathlib import Path

    from .profondeur import isolation_demandee
    dispatch = config.get("_web_dispatch") or _default_web_dispatch
    # Attendre l'enfant = le relire comme CheckAgentResult et les garde-fous le relisent
    # (enfants.lire : /api/agents/<moi>/children). L'ancienne attente lisait la route ticket
    # et `classify_ticket`, qui compte « en cours » un enfant oisif (tour clos, process chaud)
    # que CheckAgentResult dit « fini, livré » : deux vérités sur le même enfant.
    wait_verdict = config.get("_web_wait_verdict") or _attente_de_mes_enfants(config)
    wait = _attend_l_enfant(params)

    ipc_dir = os.environ.get("BOUZECODE_WEB_IPC_DIR", "")
    self_id = Path(ipc_dir).stem if ipc_dir else ""
    params = dict(params)  # l'avertissement enrichit le prompt : ne pas muter l'appel d'origine
    avertissement_wip = _avertir_travail_non_commite(params)
    body = {
        "prompt": params["prompt"],
        "typology": params.get("subagent_type", "") or "",
        "model": params.get("model", "") or "",
        "parent": self_id,
        # Projet de l'enfant. Vide (le cas NORMAL) = celui du parent, lu sur sa fiche par
        # `client_tickets.creer_ticket` (GET /api/agents/<parent>) : l'agent n'a aucun moyen
        # de connaître les slugs. Renseigné = override explicite, il prime.
        "project_slug": params.get("project_slug", "") or "",
        # Isolation DÉCIDÉE PAR LE PARENT (2026-10-05) selon le besoin réel : `shared` par
        # défaut (l'enfant peut encore demander son worktree via `Environment`), `worktree`
        # pour des enfants parallèles sur le même dépôt, `worktree+venv` s'il touche aux
        # dépendances. Valeur invalide : refusée plus haut par `_agent_tool`.
        "isolation": isolation_demandee(params)[0] or "shared",
        # worktree créé DEPUIS cette branche (point de départ) — l'enfant reste sur une branche neuve
        "resume_branch": params.get("resume_branch", "") or "",
        # branche EXISTANTE sur laquelle l'enfant travaille : elle est sortie telle quelle dans
        # son worktree, ses commits y atterrissent. Le serveur REFUSE le dispatch si elle est
        # inconnue ou déjà sortie ailleurs — jamais de repli silencieux sur une branche neuve.
        "work_branch": params.get("work_branch", "") or "",
        # defer : le serveur crée le ticket et renvoie son id AVANT le provisioning
        # worktree + spawn (qui dépassent 30 s). Sans ça l'appel timeoutait, le manager
        # croyait à un échec et RE-dispatchait → tickets dupliqués.
        "defer": True,
        **_lancement(params, config),
    }
    result = dispatch(body)

    # ÉCHECS = ERREURS D'OUTIL (préfixe `Error:`, la convention du registre — cf.
    # core.tool_registry). Rendus jadis comme un compte rendu neutre, ils étaient
    # indiscernables d'un succès : le manager clôturait son tour en affirmant « ticket
    # dispatché » alors que ZÉRO enfant existait. `_bg_agent_launched` n'est JAMAIS posé sur
    # ces chemins (retour anticipé) : sans ça le turn-protocol croirait un enfant en vol.
    if result.get("code") == "projet_requis":
        slugs = ", ".join(result.get("projets_ouverts") or []) or "(aucun)"
        # Troisième cause, distincte du refus applicatif et du proxy : le serveur ne
        # reconnaît plus l'agent APPELANT. Sans ce cas nommé, un manager dont
        # l'enregistrement a été purgé sous lui lisait « aucun projet ouvert » et cherchait
        # une erreur de configuration — le vrai problème étant sa propre disparition.
        if result.get("parent_unknown"):
            return ("Error: dispatch REFUSÉ, aucun enfant n'a été créé — LE SERVEUR NE TE "
                    "CONNAÎT PLUS : ton enregistrement d'agent a disparu de sa flotte "
                    "(purge, archivage ou nettoyage pendant que tu tournais), donc tu "
                    "n'hérites plus d'aucun projet. Ce n'est NI un problème de réseau NI un "
                    f"proxy. Relance Agent en nommant project_slug parmi : {slugs}, et "
                    "signale-le : tes réveils automatiques sont perdus eux aussi.")
        return ("Error: dispatch REFUSÉ, aucun enfant n'a été créé — projet indéterminé "
                "(ton agent n'est rattaché à aucun projet ouvert, donc rien à hériter). "
                f"Relance Agent avec project_slug parmi : {slugs}.")
    if not result.get("routed"):
        # `error` est le motif ACTIONNABLE posé par le serveur (ex. branche demandée déjà
        # sortie ailleurs, avec le worktree occupant nommé). Le rendre tel quel plutôt que noyé
        # dans le dump du dict : c'est ce que le manager doit lire pour corriger son appel.
        if result.get("error"):
            return f"Error: dispatch REFUSÉ, aucun enfant n'a été créé — {result['error']}"
        return f"Error: dispatch ÉCHOUÉ, aucun enfant n'a été créé — réponse serveur : {result}"
    ticket_id = result["ticket_id"]
    _noter_l_enfant(config, ticket_id, params)
    ref = result.get("key") or f"ticket/{ticket_id}"  # 'key' absente en mode defer
    head = (
        f"Ticket {ticket_id} dispatché (projet {result.get('project_name', '?')}, "
        f"typologie {result.get('typology', '?')}, {ref})."
    )
    # Dernier maillon du garde-fou de périmètre. Le serveur détecte le doublon et le mandat
    # read-only non tenu, pose ses drapeaux sur le ticket et renvoie `scope_warnings`
    # (scope_guard.review_dispatch -> routes/work/fleet.py). Mais le manager ne lit NI les
    # tickets NI les commentaires : son seul canal est le tool_result de son appel Agent. Sans
    # ce relais, toute la chaîne s'exécutait pour rien — un garde-fou complet et muet.
    # Ajouté à `head`, donc rendu dans les DEUX modes : en attente comme en fond.
    for avertissement in result.get("scope_warnings") or []:
        head += f"\n⚠️ {avertissement}"
    if avertissement_wip:
        head += f"\n{avertissement_wip}"

    if wait:
        # `project_slug` vient de la réponse serveur (même source que le message de succès
        # ci-dessus) : l'agent n'a aucun moyen de le deviner, et la route ticket l'exige.
        return _wait_for_child(wait_verdict, ticket_id,
                               result.get("project_slug") or "", head, config)

    # BACKGROUND : rend la main tout de suite, le manager CONTINUE ce tour.
    config["_bg_agent_launched"] = True
    return (
        f"{head}\n"
        "Lancé EN FOND — la main t'est rendue immédiatement. Tu peux lancer d'autres "
        "Agent ou poursuivre ton travail DANS CE MÊME TOUR. Ne poll pas, pas de "
        "Start-Sleep : quand tu as besoin de son résultat, attends-le avec "
        f"CheckAgentResult(task_id='{ticket_id}', wait=true). Tu ne pourras pas clore tant "
        "qu'il travaille (sauf manager : clore est ta façon d'attendre, tu seras réveillé)."
    )


def _lancement(params: dict, config: dict) -> dict:
    """Ce que le parent relira de ce lancement (ListAgentTasks) : son tour et le nom donné ;
    et la raison d'un doublon assumé (un second enfant sur le périmètre d'un enfant ENCORE
    ACTIF est refusé par le serveur sans elle)."""
    return {"name": str(params.get("name") or ""), "parent_turn": _mon_tour(config),
            "doublon_assume": str(params.get("doublon_assume") or "")}


def _mon_tour(config: dict) -> int:
    state = config.get("_state")
    return int(getattr(state, "turn_count", 0) or config.get("_turn_count") or 0)


def _noter_l_enfant(config: dict, ticket_id: str, params: dict) -> None:
    """Le lancement entre dans la note Methodology, écrit par le HARNAIS : il ne dépend ni de
    ce que le modèle pense à noter, ni d'un résultat d'outil qui quitte le fil au tour suivant
    (essai du 2026-09-25 : la racine a relancé le même enfant deux tours plus tard, puis a nié
    l'avoir lancé)."""
    from ..context_manager.methodology import append_child_launch_to_methodology
    append_child_launch_to_methodology(config.get("_context_state"), ticket_id, _mon_tour(config),
                                       params.get("name", "") or "", params.get("prompt", ""))
