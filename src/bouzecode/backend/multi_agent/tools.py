# [desc] Registers multi-agent tools (spawn, message, check, list) into the central tool registry. [/desc]
"""Multi-agent tool registrations.

Registers the following tools into the central tool_registry:
  Agent            — spawn a sub-agent (sync or background)
  SendMessage      — send a message to a named background agent
  CheckAgentResult — check status/result of a background agent
  ListAgentTasks   — list all active/finished agent tasks
  ListAgentTypes   — list available agent type definitions
"""
from __future__ import annotations

import os
import sys
import time

from ..core.tool_registry import ToolDef, register_tool


# Wait-loop tuning for terminal sub-agents (module-level so tests can monkeypatch).
_TERMINAL_WAIT_TIMEOUT = 300  # seconds before giving up on the result file
_TERMINAL_WAIT_INTERVAL = 2   # seconds between result-file existence checks


# ── Singleton manager ──────────────────────────────────────────────────────

_agent_manager: SubAgentManager | None = None


def get_agent_manager() -> "SubAgentManager":
    """Return (and lazily create) the process-wide SubAgentManager."""
    global _agent_manager
    if _agent_manager is None:
        from .manager import SubAgentManager
        _agent_manager = SubAgentManager()
    return _agent_manager


# ── Role-based spawn guard ─────────────────────────────────────────────────

# The manager is a read-only dispatcher: it must characterize a SPECIALIZED
# typology for each ticket, never fall back to a generic un-scoped agent.
# Spawning 'general-purpose' or 'default' from a manager defeats that purpose.
_MANAGER_FORBIDDEN_TYPES = {"general-purpose", "default"}


def _manager_type_guard(config: dict, subagent_type: str) -> str | None:
    """Return a refusal message if the CURRENT profile is 'manager' and it tries
    to spawn a generic un-specialized agent; otherwise None (allowed).

    Pure function (config in, message out) — testable without any mock/patch.
    """
    if config.get("_agent_type") != "manager":
        return None
    if (subagent_type or "").strip().lower() not in _MANAGER_FORBIDDEN_TYPES:
        return None
    return (
        f"Refused: a manager cannot spawn subagent_type "
        f"'{subagent_type}'. The manager must characterize a SPECIALIZED "
        "typology for each ticket (e.g. coder, frontend, meta-agent) — "
        "never the generic 'general-purpose' or 'default' agent. "
        "Use ListAgentTypes to pick a specialized type."
    )


# ── Tool implementations ───────────────────────────────────────────────────

def _is_terminal_mode() -> bool:
    """True when bouzecode is running in a real terminal (not BouzéqUI)."""
    from ..tools.interaction import is_web_ipc_active
    return not is_web_ipc_active() and sys.stdin.isatty()


# Wait-loop tuning for terminal sub-agents. Module-level so tests can monkeypatch.
_TERMINAL_WAIT_TIMEOUT = 300
_TERMINAL_WAIT_INTERVAL = 2


def _spawn_terminal_agent(params: dict, config: dict) -> str:
    """Spawn sub-agent in a new terminal window and optionally wait for result."""
    import tempfile
    import time
    from pathlib import Path
    from .terminal import spawn_in_terminal

    mgr = get_agent_manager()
    prompt = params["prompt"]
    wait = params.get("wait", True)
    name = params.get("name", "")
    subagent_type = params.get("subagent_type", "")
    model_override = params.get("model", "")

    # Build effective config for the sub-agent process
    eff_config = {k: v for k, v in config.items() if not k.startswith("_")}
    if model_override:
        eff_config["model"] = model_override
    # Re-inject the keep-open debug flag (stripped above because it starts with "_")
    if config.get("_terminal_keep_open"):
        eff_config["_terminal_keep_open"] = True

    # Create task for tracking
    task = mgr.create_task(prompt=prompt, depth=config.get("_depth", 0), name=name)
    if subagent_type:
        task.agent_type = subagent_type
    task.model = eff_config.get("model", "")
    task.status = "running"

    # Result file for inter-process communication
    result_file = os.path.join(tempfile.gettempdir(), f"bouzecode_agent_{task.id}.result.txt")

    proc = spawn_in_terminal(prompt, result_file, eff_config)

    if not wait:
        info_parts = [
            f"Task ID: {task.id}",
            f"Name: {task.name}",
            f"Status: running (in new terminal)",
        ]
        if subagent_type:
            info_parts.append(f"Type: {subagent_type}")
        info_parts.append(f"Result file: {result_file}")
        info_parts.append("The agent is running in a separate terminal window.")
        return "\n".join(info_parts)

    # Poll for the APPEARANCE of the result file (wait mode).
    # NOTE: we must NOT rely on proc.poll() here — launchers like wt.exe and
    # "cmd /c start" return IMMEDIATELY (the real work happens in a detached
    # child process), so proc.poll() is non-None on the very first iteration
    # and the result file would be read before the child has written it.
    timeout = _TERMINAL_WAIT_TIMEOUT
    poll_interval = _TERMINAL_WAIT_INTERVAL
    elapsed = 0
    result_path = Path(result_file)
    while elapsed < timeout:
        if result_path.exists():
            break
        time.sleep(poll_interval)
        elapsed += poll_interval

    # Read result
    if result_path.exists():
        result = result_path.read_text(encoding="utf-8").strip()
        result_path.unlink(missing_ok=True)
        task.status = "completed"
        task.result = result
    else:
        task.status = "failed"
        task.result = f"No result file produced (timed out after {timeout}s)"
        result = task.result

    header = f"[Agent (terminal): {task.name}"
    if subagent_type:
        header += f" ({subagent_type})"
    header += "]"
    return f"{header}\n\n{result or '(no output)'}"


_DISPATCH_URL = "http://127.0.0.1:5056/api/dispatch"


def _default_web_dispatch(body: dict) -> dict:
    """POST /api/dispatch (écrivain unique → pas de race sur le fichier tickets).
    Timeout large : même en mode defer, la création du ticket peut suivre un classify
    LLM. 180 s couvre largement sans jamais faire de faux timeout → pas de doublon.

    Passe par `core.local_http`, qui bâtit un opener SANS proxy : cet appel vise la boucle
    locale et ne doit JAMAIS partir dans le proxy d'entreprise. Avec `urlopen` (opener par
    défaut) il en dépendait, et un `NO_PROXY` incomplet le faisait échouer en
    `HTTP Error 407: Proxy Authentication Required` — panne du 2026-07-28."""
    from ..core.local_http import local_json
    return local_json("POST", _DISPATCH_URL, body, timeout=180)


# Route de DÉTAIL d'un ticket (une seule ligne, peu coûteuse). Il n'existe AUCUNE route
# `/api/ticket/<id>` au singulier et sans slug : elle répondait 404 à TOUS les coups, donc
# l'attente de l'enfant échouait toujours et un dispatch RÉUSSI était rapporté comme un
# échec (faux négatif observé le 2026-07-27). Le slug vient de la réponse de /api/dispatch.
_TICKET_DETAIL_URL = "http://127.0.0.1:5056/api/tickets/{slug}/{ticket_id}"

# Classements de vivacité où l'enfant N'A PAS rendu la main : on continue d'attendre.
# Tout AUTRE classement rend la main ('stalled' = travail livré en attente d'une décision
# du manager, 'delivered' = issue actée, 'crashed', ou un état futur encore inconnu).
# Le complément est pris dans CE sens volontairement : rendre la main trop tôt est
# rattrapable (le manager relit le ticket), attendre à tort fige le manager 30 minutes.
_LIVENESS_STILL_WORKING = frozenset({"running", "launching"})

_WAIT_POLL_INTERVAL = 10   # s entre deux sondages du ticket enfant
_WAIT_TIMEOUT = 1800       # s (30 min) avant de rendre la main sans verdict


def _get_json(url: str) -> dict:
    """GET JSON. Seam d'injection de l'attente : les tests fournissent leur propre getter,
    ce qui rend `_default_web_wait_verdict` testable sans réseau et sans mock.
    Appel LOCAL → `core.local_http`, jamais proxyfié (cf. panne 407 du 2026-07-28)."""
    from ..core.local_http import local_json
    return local_json("GET", url, timeout=60)


def _child_still_working(ticket: dict) -> bool:
    """L'enfant tourne-t-il encore ? Tranché par `liveness.classify_ticket`, la source
    UNIQUE de vérité du serveur (croise le PID de l'agent et sa session sur disque) — pas
    par une liste de libellés recopiée ici, qui redériverait au premier statut ajouté.

    Pourquoi PAS le champ `status` du ticket : la route de détail ne rafraîchit pas l'état
    live des runs (il n'est même pas persisté — `refresh_verdicts` ne l'écrit jamais),
    donc `derive_status` y annonce « à relire » pour un agent qui TOURNE. Vérifié en direct
    sur les tickets 76ccd35a / c89891bf : `status`='à relire', `liveness`='running'. S'y fier
    rendrait la main au parent dans la seconde qui suit le dispatch."""
    from bouzecode.web_v2.services.work import liveness
    return liveness.classify_ticket(ticket) in _LIVENESS_STILL_WORKING


def _child_report(ticket: dict) -> str:
    """Compte rendu de l'enfant qui a rendu la main, lu aux MÊMES endroits que le digest de
    réveil du parent (`wake.ticket_outcome`) : l'issue du ticket, puis les verdicts portés
    par ses RUNS (`ticket["runs"][*]["verdict"]`). Le ticket lui-même n'a jamais porté de
    champ `verdict` — le lire là (ancien code) ne pouvait rien rendre."""
    from bouzecode.web_v2.services.work import wake
    lines = [wake.ticket_outcome(ticket)]
    lines += [f"{run.get('kind') or 'run'} → {run['verdict']}"
              for run in ticket.get("runs") or []
              if isinstance(run, dict) and run.get("verdict")]
    return "\n".join(lines)


def _default_web_wait_verdict(ticket_id: str, project_slug: str, *,
                              get_json=_get_json, sleep=time.sleep,
                              now=time.monotonic, timeout: int = _WAIT_TIMEOUT) -> str:
    """Sonde le ticket enfant jusqu'à ce qu'il rende la main, puis renvoie son compte rendu.
    Sert le mode PAUSE (défaut) où le manager bloque sur son enfant.

    `get_json` / `sleep` / `now` sont injectables : la boucle temporisée se teste ainsi de
    bout en bout, sans réseau ni horloge réelle, et sans aucun mock."""
    if not project_slug:
        raise ValueError(
            "project_slug absent de la réponse de dispatch : l'URL du ticket "
            "(/api/tickets/<slug>/<id>) ne peut pas être construite")
    url = _TICKET_DETAIL_URL.format(slug=project_slug, ticket_id=ticket_id)
    deadline = now() + timeout
    while now() < deadline:
        ticket = get_json(url)
        if not _child_still_working(ticket):
            return _child_report(ticket)
        sleep(_WAIT_POLL_INTERVAL)
    return (f"Ticket {ticket_id} : toujours en cours après {timeout} s d'attente. "
            "Le ticket EXISTE et son agent tourne — ne le redispatche pas. Tu seras "
            "ré-invoqué automatiquement avec son verdict quand il aura terminé.")


def _wait_for_child(wait_verdict, ticket_id: str, project_slug: str,
                    head: str, config: dict) -> str:
    """Bloque sur l'enfant et rend son verdict. Si c'est l'ATTENTE qui échoue, le retour
    annonce d'abord que le TICKET EXISTE : une attente cassée n'est PAS un dispatch raté.
    Un manager qui croit son dispatch raté redispatche → tickets EN DOUBLE (c'est le faux
    négatif du 2026-07-27, miroir exact du faux succès corrigé le matin même). Le retour ne
    porte donc JAMAIS le préfixe `Error:`, réservé au cas « aucun enfant n'a été créé »."""
    try:
        verdict = wait_verdict(ticket_id, project_slug)
    except Exception as exc:  # noqa: BLE001 — 404/refus réseau/JSON illisible : même issue
        # L'enfant EST en vol : on pose le drapeau comme en mode fond pour que le
        # turn-protocol laisse le tour ouvert au lieu de pousser vers FinalAnswer.
        config["_bg_agent_launched"] = True
        return (
            f"{head}\n"
            f"⚠ LE TICKET EXISTE ET SON AGENT TOURNE — seule l'ATTENTE a échoué "
            f"({type(exc).__name__}: {exc}). NE REDISPATCHE PAS ce travail, tu créerais un "
            f"ticket EN DOUBLE. Tu seras ré-invoqué automatiquement avec le verdict de "
            f"l'enfant quand il aura terminé ; d'ici là tu peux suivre son état avec "
            f"Fleet(action='list') ou le ré-instruire avec MessageAgent(ticket_id="
            f"'{ticket_id}')."
        )
    return f"{head}\nVerdict de l'enfant :\n{verdict}"


def _spawn_web_ticket_agent(params: dict, config: dict) -> str:
    """Sous-agent en mode BouzéqUI web = TOOL CALL LONG à 2 modes (PAS une fin de tour).

    Crée un TICKET gouverné via le serveur (écrivain unique → pas de race) et attache
    parent=<self> pour être ré-invoqué automatiquement quand l'enfant aura fini
    (cf. web_v2.services.work.wake).

    Modes :
      - BACKGROUND (défaut, wait=False) : dispatch le ticket, RÉ-INVITE le manager à
        continuer son tour (lancer d'autres Agent, poursuivre son travail). Pose
        config["_bg_agent_launched"]=True pour que le turn-protocol NE nudge PAS vers
        FinalAnswer ce tour-ci tant qu'un Agent lancé maintenant tourne.
      - wait=True : bloque jusqu'au verdict de l'enfant et le renvoie.

    Dépendances injectables (testabilité sans mock.patch) :
      - config["_web_dispatch"](body:dict)->dict  (défaut = POST urllib réel)
      - config["_web_wait_verdict"](ticket_id:str, project_slug:str)->str
        (défaut = poll urllib réel ; le slug est REQUIS, la route ticket en a besoin)
    """
    from pathlib import Path

    dispatch = config.get("_web_dispatch") or _default_web_dispatch
    wait_verdict = config.get("_web_wait_verdict") or _default_web_wait_verdict
    # Sémantique alignée sur Bash : `background=False` (DÉFAUT) = le parent SE MET EN PAUSE
    # (bloque jusqu'au verdict de l'enfant) ; `background=True` = rend la main, le parent
    # CONTINUE son tour. `wait` reste honoré si fourni explicitement (rétrocompat : wait=False
    # → continue, comme background=True ; wait=True → pause). Aucun des deux → pause.
    background = bool(params.get("background", False))
    wait = bool(params["wait"]) if "wait" in params else (not background)

    ipc_dir = os.environ.get("BOUZECODE_WEB_IPC_DIR", "")
    self_id = Path(ipc_dir).stem if ipc_dir else ""
    body = {
        "prompt": params["prompt"],
        "typology": params.get("subagent_type", "") or "",
        "model": params.get("model", "") or "",
        "parent": self_id,
        # Projet de l'enfant. Vide (le cas NORMAL) = le serveur le fait HÉRITER du parent
        # via `parent` (cf. web_v2.services.work.projects.slug_of_agent) : l'agent n'a aucun
        # moyen de connaître les slugs. Renseigné = override explicite, il prime.
        "project_slug": params.get("project_slug", "") or "",
        # Environnement demandé pour l'enfant : shared (défaut) | worktree | worktree+venv.
        # C'est le MANAGER qui décide, parce que lui seul sait combien d'agents écrivent en
        # parallèle et si la tâche touche aux dépendances (cf. schéma de l'outil).
        "isolation": params.get("isolation", "") or "shared",
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
    }
    result = dispatch(body)

    # ÉCHECS = ERREURS D'OUTIL (préfixe `Error:`, la convention du registre — cf.
    # core.tool_registry). Rendus jadis comme un compte rendu neutre, ils étaient
    # indiscernables d'un succès : le manager clôturait son tour en affirmant « ticket
    # dispatché » alors que ZÉRO enfant existait. `_bg_agent_launched` n'est JAMAIS posé sur
    # ces chemins (retour anticipé) : sans ça le turn-protocol croirait un enfant en vol.
    if result.get("needs_project"):
        slugs = ", ".join(s["slug"] for s in result.get("suggestions") or []) or "(aucun)"
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
        "Agent ou poursuivre ton travail DANS CE MÊME TOUR. Tu seras aussi ré-invoqué "
        "automatiquement avec son verdict quand il aura terminé. Ne poll pas, pas de "
        "Start-Sleep."
    )


_MESSAGE_URL = "http://127.0.0.1:5056/api/agent/message"


def _message_agent(params: dict, config: dict) -> str:
    """Ré-instruit un agent enfant DÉJÀ lancé (même agent, contexte gardé), identifié
    par son ticket_id. En mode BouzéqUI web : POST /api/agent/message. Hors web : l'outil
    n'a pas de flotte de tickets gouvernés → message clair, pas de fallback."""
    from ..tools.interaction import is_web_ipc_active
    if not is_web_ipc_active():
        return ("MessageAgent n'est disponible qu'en mode BouzéqUI web (il ré-instruit un "
                "ticket enfant gouverné). Hors web, il n'y a pas de flotte à contacter.")

    from ..core.local_http import LocalServerError, local_json

    ticket_id = params["ticket_id"]
    body = {"ticket_id": ticket_id, "text": params["text"]}
    try:
        result = local_json("POST", _MESSAGE_URL, body, timeout=60)
    except LocalServerError as exc:
        # 404 ticket inconnu / 409 agent occupé : `local_http` a déjà extrait le motif
        # serveur, et nomme le proxy si la requête n'a jamais atteint bouzecode.
        return f"Message NON transmis au ticket {ticket_id} : {exc}"
    if result.get("ok"):
        return f"Message transmis au ticket {ticket_id}."
    return f"Message NON transmis au ticket {ticket_id} : {result.get('error', 'erreur inconnue')}"


def _agent_tool(params: dict, config: dict) -> str:
    """Spawn a sub-agent, routed by execution context:
      - terminal (tty, no web IPC) → new terminal window;
      - BouzéqUI web (web IPC active) → governed web TICKET + auto wake-on-completion;
      - pure headless → in-process SubAgentManager thread (fallback).

    Reads from config:
      _system_prompt  — injected by agent.py run(), used as base system prompt
      _depth          — current nesting depth (prevents infinite recursion)
    """
    from ..tools.interaction import is_web_ipc_active

    # Role-based guard FIRST (before any routing/spawn): a manager may only
    # dispatch specialized typologies, never 'general-purpose' / 'default'.
    refusal = _manager_type_guard(config, params.get("subagent_type", ""))
    if refusal is not None:
        return refusal

    # Auto-dispatch by context: terminal → window, web → governed ticket
    if _is_terminal_mode():
        return _spawn_terminal_agent(params, config)
    if is_web_ipc_active():
        return _spawn_web_ticket_agent(params, config)

    mgr = get_agent_manager()

    prompt = params["prompt"]
    wait = params.get("wait", True)
    isolation = params.get("isolation", "")
    name = params.get("name", "")
    model_override = params.get("model", "")
    subagent_type = params.get("subagent_type", "")

    system_prompt = config.get("_system_prompt", "You are a helpful assistant.")
    depth = config.get("_depth", 0)

    # Strip private keys before passing to sub-agent
    eff_config = {k: v for k, v in config.items() if not k.startswith("_")}
    if model_override:
        eff_config["model"] = model_override

    # Resolve the agent profile (system builtin or user/project/catalog profile)
    profile = None
    if subagent_type:
        from ..profiles.discovery import resolve_agent_profile
        profile = resolve_agent_profile(subagent_type)
        if profile is None:
            return (
                f"Error: unknown subagent_type '{subagent_type}'. "
                "Use ListAgentTypes to see available types."
            )

    task = mgr.spawn(
        prompt, eff_config, system_prompt,
        depth=depth,
        profile=profile,
        isolation=isolation,
        name=name,
    )

    if task.status == "failed":
        return f"Error spawning agent: {task.result}"

    if wait:
        mgr.wait(task.id, timeout=300)
        result = task.result or f"(no output — status: {task.status})"
        header = f"[Agent: {task.name}"
        if subagent_type:
            header += f" ({subagent_type})"
        if task.worktree_branch:
            header += f", branch: {task.worktree_branch}"
        header += "]"
        return f"{header}\n\n{result}"
    else:
        info_parts = [f"Task ID: {task.id}", f"Name: {task.name}", f"Status: {task.status}"]
        if subagent_type:
            info_parts.append(f"Type: {subagent_type}")
        if task.worktree_branch:
            info_parts.append(f"Worktree branch: {task.worktree_branch}")
        info_parts.append("Use CheckAgentResult or SendMessage to interact with this agent.")
        return "\n".join(info_parts)


def _send_message(params: dict, config: dict) -> str:
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
    mgr = get_agent_manager()
    task_id = params["task_id"]
    task = mgr.tasks.get(task_id)
    if task is None:
        return f"Error: no task with id '{task_id}'"
    lines = [f"Status: {task.status}", f"Name: {task.name}"]
    if task.worktree_branch:
        lines.append(f"Worktree branch: {task.worktree_branch}")
    if task.result:
        lines.append(f"\nResult:\n{task.result}")
    return "\n".join(lines)


def _list_agent_tasks(params: dict, config: dict) -> str:
    mgr = get_agent_manager()
    tasks = mgr.list_tasks()
    if not tasks:
        return "No sub-agent tasks."
    lines = ["ID           | Name     | Status    | Worktree branch | Prompt"]
    lines.append("-------------|----------|-----------|-----------------|------")
    for t in tasks:
        prompt_short = t.prompt[:50] + ("..." if len(t.prompt) > 50 else "")
        wt = t.worktree_branch[:15] if t.worktree_branch else "-"
        lines.append(f"{t.id} | {t.name[:8]:8s} | {t.status:9s} | {wt:15s} | {prompt_short}")
    return "\n".join(lines)


def _list_agent_types(params: dict, config: dict) -> str:
    """List agent typologies from the SAME source of truth as GET /api/typologies
    (project-local + global + extra profiles + builtin system agents), so a manager
    dispatched in the web UI enumerates exactly the kanban's typologies."""
    from bouzecode.web_v2.services.typologies import list_typologies
    typologies = list_typologies(project_path=os.getcwd())
    # 'general-purpose' / 'default' are NEVER listed by ListAgentTypes, regardless
    # of the caller: they are the generic un-scoped agents and must never be
    # proposed as a dispatchable typology (the specialized 'coder' is the default
    # coding agent instead).
    typologies = [t for t in typologies
                  if (t.get("name") or "").strip().lower() not in _MANAGER_FORBIDDEN_TYPES]
    if not typologies:
        return "No agent types available."
    lines = ["Available agent types (use the name as subagent_type):", ""]
    for t in typologies:
        desc = (t.get("description") or "").strip().split("\n", 1)[0]
        lines.append(f"  {t['name']:20s}  {desc}")
        if t.get("default_model"):
            lines.append(f"                        model: {t['default_model']}")
    lines.append("")
    lines.append(
        "Create custom agents: write a profile YAML in ~/.bouzecode/profiles/ "
        "or <project>/.bouzecode/profiles/ (see the meta-agent / creating-agents skill)."
    )
    return "\n".join(lines)


def _fleet_tool(params: dict, config: dict) -> str:
    """Manager fleet control WITHOUT shell/HTTP: lists or kills governed web agents by
    calling the Python services directly (web_v2.services.work.fleet + web.runner).

    action="list"  → agent_tree() rendered as readable text (agent_id, state, project…).
    action="kill"  → requires agent_id; resolves the live Agent via runner.list_agents()
                     and calls runner.kill_agent(agent). Clear message if not found.
    Only available in BouzéqUI web mode (there is a governed ticket fleet there)."""
    from ..tools.interaction import is_web_ipc_active
    if not is_web_ipc_active():
        return ("Fleet n'est disponible qu'en mode BouzéqUI web (il pilote la flotte de "
                "tickets gouvernés). Hors web, il n'y a pas de flotte à lister/tuer.")

    action = (params.get("action") or "").strip().lower()
    if action not in ("list", "kill"):
        return "Fleet: 'action' doit valoir 'list' ou 'kill'."

    from ...web_v2.runtime import runner
    from ...web_v2.services.work import fleet

    if action == "list":
        nodes = fleet.agent_tree().get("nodes", [])
        if not nodes:
            return "Aucun agent dans la flotte."
        lines = [f"{len(nodes)} agent(s) :"]
        for n in nodes:
            flags = []
            if n.get("suspect_dead"):
                flags.append("suspect_dead")
            if n.get("question"):
                flags.append("waiting_question")
            flag_txt = f" [{', '.join(flags)}]" if flags else ""
            parent = n.get("parent") or "-"
            lines.append(
                f"- {n.get('agent_id', '?')} | {n.get('state', '?')} | "
                f"projet={n.get('project_name') or n.get('project_slug') or '?'} | "
                f"parent={parent} | {n.get('title') or ''}{flag_txt}"
            )
        return "\n".join(lines)

    # action == "kill"
    agent_id = (params.get("agent_id") or "").strip()
    if not agent_id:
        return "Fleet kill: 'agent_id' requis."
    target = next((a for a in runner.list_agents() if a.agent_id == agent_id), None)
    if target is None:
        return f"Fleet kill: agent introuvable (agent_id={agent_id}). Utilise action='list'."
    runner.kill_agent(target)
    return f"Agent {agent_id} tué (kill demandé)."


# ── Tool registrations ─────────────────────────────────────────────────────

register_tool(ToolDef(
    name="Agent",
    schema={
        "name": "Agent",
        "description": (
            "Spawn a sub-agent to handle a task autonomously. Supports specialized agent "
            "types (system agents 'general-purpose', 'meta-agent', 'manager', or any profile "
            "in ~/.bouzecode/profiles or <project>/.bouzecode/profiles), a per-agent "
            "environment (`isolation`), and background execution.\n\n"
            "NOTHING runs automatically after the child delivers: no test gate, no "
            "validator, no merge. YOU decide what happens next — read its report, "
            "optionally spawn a validator, and integrate its branch when you judge it ready."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Task description for the sub-agent",
                },
                "subagent_type": {
                    "type": "string",
                    "description": (
                        "Agent profile name: 'general-purpose' (default), 'meta-agent', "
                        "'manager', or any custom profile. "
                        "Use ListAgentTypes to see all available types."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Human-readable name for this agent instance. "
                        "Makes it addressable by name while it runs in the background "
                        "(with whichever agent-messaging tool your registry offers)."
                    ),
                },
                "model": {
                    "type": "string",
                    "description": "Model override for this specific agent (optional)",
                },
                "background": {
                    "type": "boolean",
                    "description": (
                        "In web (manager) mode, Agent is a LONG tool call. Like Bash: "
                        "background=false (DEFAULT) PAUSES you — the call blocks until the "
                        "sub-agent finishes and returns its verdict. background=true returns "
                        "immediately: you keep your turn and may launch more Agents or continue "
                        "working (you are still re-invoked with the verdict when the child ends). "
                        "(In headless/in-process mode the default remains synchronous wait.)"
                    ),
                },
                "wait": {
                    "type": "boolean",
                    "description": (
                        "LEGACY alias (prefer `background`). wait=true = pause (block until "
                        "verdict); wait=false = continue (background). If provided, it overrides "
                        "`background`."
                    ),
                },
                "isolation": {
                    "type": "string",
                    "enum": ["shared", "worktree", "worktree+venv"],
                    "description": (
                        "Environment provisioned for this agent. YOU choose it — you are the "
                        "only one who knows how many agents write in parallel and whether the "
                        "task touches dependencies.\n"
                        "- 'shared' (DEFAULT): nothing provisioned, the agent works in the main "
                        "checkout. Use it for a read-only agent, a short task, or when it is the "
                        "ONLY writer on that repo. Cheapest — it starts immediately.\n"
                        "- 'worktree': a dedicated git worktree, NO venv. Use it as soon as TWO "
                        "OR MORE agents will write in the same repo at the same time. A git "
                        "worktree is nearly free, so prefer it over risking a collision.\n"
                        "- 'worktree+venv': dedicated worktree AND venv. Use it ONLY when the "
                        "agent will touch dependencies (pyproject.toml, requirements.txt, "
                        "installing a package). The venv is a full `uv sync` per agent — it is "
                        "what makes a launch take 30 s, so never ask for it 'just in case'.\n"
                        "Safety net: if you launch a 'shared' agent on a repo where another "
                        "'shared' agent is already running, the server upgrades it to 'worktree' "
                        "and says so in a ticket comment."
                    ),
                },
                "resume_branch": {
                    "type": "string",
                    "description": (
                        "POINT DE DÉPART seulement : le worktree de l'enfant est créé DEPUIS "
                        "cette branche, mais l'enfant travaille sur une branche NEUVE "
                        "`agent/<ticket>`. Sa livraison n'atterrit donc PAS sur la branche "
                        "nommée ici. Si tu veux qu'il livre SUR une branche précise, c'est "
                        "`work_branch` qu'il te faut."
                    ),
                },
                "work_branch": {
                    "type": "string",
                    "description": (
                        "Branche EXISTANTE sur laquelle l'enfant doit travailler : elle est "
                        "sortie telle quelle dans son worktree et ses commits y vont "
                        "DIRECTEMENT. Utilise-le dès que la mission dit « mets à jour la "
                        "branche X » ou « ta branche de travail = X » — l'écrire seulement en "
                        "prose dans le prompt ne provisionne RIEN, l'enfant recevrait une "
                        "branche neuve et son travail resterait invisible sur X.\n"
                        "Le serveur REFUSE le dispatch (aucun ticket, aucun enfant) si la "
                        "branche n'existe pas, ou si un autre worktree l'a déjà sortie — le "
                        "message nomme alors le worktree occupant. Deux agents ne peuvent pas "
                        "travailler sur la même branche en même temps."
                    ),
                },
                "project_slug": {
                    "type": "string",
                    "description": (
                        "Projet dans lequel lancer l'enfant. LAISSE VIDE par défaut : "
                        "l'enfant HÉRITE automatiquement de ton propre projet. Ne le "
                        "renseigne que pour dispatcher dans un AUTRE projet, ou si un "
                        "dispatch a été refusé faute de projet (le message d'erreur liste "
                        "alors les slugs valides)."
                    ),
                },
            },
            "required": ["prompt"],
        },
    },
    func=_agent_tool,
    read_only=False,
    concurrent_safe=False,
))

register_tool(ToolDef(
    name="MessageAgent",
    schema={
        "name": "MessageAgent",
        "description": (
            "Envoie une nouvelle instruction à un agent enfant DÉJÀ lancé (même agent, "
            "contexte gardé), identifié par son ticket_id. À utiliser pour ré-orienter ou "
            "compléter la consigne d'un enfant en cours au lieu d'en spawner un nouveau. "
            "Refuse (message d'erreur) si l'agent tourne encore ou si le ticket est "
            "introuvable. Disponible uniquement en mode BouzéqUI web."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "Id du ticket de l'agent enfant à ré-instruire.",
                },
                "text": {
                    "type": "string",
                    "description": "Nouvelle instruction / message à lui transmettre.",
                },
            },
            "required": ["ticket_id", "text"],
        },
    },
    func=_message_agent,
    read_only=False,
    concurrent_safe=False,
))

register_tool(ToolDef(
    name="SendMessage",
    schema={
        "name": "SendMessage",
        "description": (
            "Send a follow-up message to a running background agent. "
            "The message is queued and processed after the agent finishes its current work. "
            "Reference agents by the name set via Agent(name=...) or by task ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to":      {"type": "string", "description": "Agent name or task ID"},
                "message": {"type": "string", "description": "Message to send to the agent"},
            },
            "required": ["to", "message"],
        },
    },
    func=_send_message,
    read_only=False,
    concurrent_safe=True,
))

register_tool(ToolDef(
    name="CheckAgentResult",
    schema={
        "name": "CheckAgentResult",
        "description": "Check the status and result of a spawned sub-agent task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID returned by Agent tool"},
            },
            "required": ["task_id"],
        },
    },
    func=_check_agent_result,
    read_only=True,
    concurrent_safe=True,
))

register_tool(ToolDef(
    name="ListAgentTasks",
    schema={
        "name": "ListAgentTasks",
        "description": "List all sub-agent tasks and their statuses.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    func=_list_agent_tasks,
    read_only=True,
    concurrent_safe=True,
))

register_tool(ToolDef(
    name="ListAgentTypes",
    schema={
        "name": "ListAgentTypes",
        "description": (
            "List all available agent types (built-in and custom). "
            "Use the type names as subagent_type when calling Agent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    func=_list_agent_types,
    read_only=True,
    concurrent_safe=True,
))

register_tool(ToolDef(
    name="Fleet",
    schema={
        "name": "Fleet",
        "description": (
            "Pilote la flotte d'agents gouvernés SANS shell brut ni HTTP. "
            "action='list' liste tous les agents (id, état, projet, parent). "
            "action='kill' arrête un agent actif (agent_id requis). "
            "Disponible uniquement en mode BouzéqUI web."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "kill"],
                    "description": "'list' pour lister les agents, 'kill' pour en tuer un.",
                },
                "agent_id": {
                    "type": "string",
                    "description": "Id de l'agent à tuer (requis si action='kill').",
                },
            },
            "required": ["action"],
        },
    },
    func=_fleet_tool,
    read_only=False,
    concurrent_safe=False,
))
