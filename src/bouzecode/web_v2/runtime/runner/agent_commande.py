# [desc] Ligne de commande, environnement et contrôle des clés provider des process d'agents. [/desc]
"""Ce qui part au process d'un agent : commande `python -m bouzecode`, env (PYTHONPATH,
identité de ticket, venv de base), arguments de profil, garde des clés du provider."""
from __future__ import annotations

from bouzecode.paths import project_dir as bouzecode_project_dir
import logging
import os
import sys
from pathlib import Path

from .. import venv_env
from .agent_fiche import Agent


# Sentinelle de `parent` pour un agent lancé À LA MAIN depuis l'UI. Ce n'est PAS une parenté :
# aucun manager ne l'a créé, et il a un utilisateur qui reviendra lui écrire. Défini ici, au
# plus bas niveau, parce que c'est ici qu'on décide ce qui part dans l'env du process spawné
# (`_ticket_env`) ; `services.work.dispatch` le ré-exporte pour ses propres lectures, afin que
# la chaîne « lancé à la main » n'ait qu'UNE définition.
MANUAL_PARENT = "dispatcher:manual"
#: `creationflags` des process d'agents. 0 pour le serveur ; la CLI (`bouzecode tickets`) les
#: détache de SA console (nouveau groupe, console cachée) : un Ctrl+C ou la fermeture du
#: terminal arrête le suivi, jamais l'agent (cf. `ui/tickets_cli`).
DRAPEAUX_DE_SPAWN = 0


def _bouzecode_launch_cmd() -> list[str]:
    """Launch bouzecode via `python -m bouzecode` — avoids Windows .exe shim file locks.
    -P (PYTHONSAFEPATH) : le cwd de l'agent ne doit pas pouvoir shadower le package
    bouzecode (ex. projet avec un bouzecode.py racine, comme bouzecode_oss)."""
    return [sys.executable, "-P", "-m", "bouzecode"]


def _agent_cmd() -> list[str]:
    """Début de ligne de commande COMMUN à tout lancement d'agent : premier spawn, reprise,
    réveil. `--loud` active le thinking (natif, via l'API) et n'ajoute plus rien au prompt
    système ; il reste commun à tous les lancements pour que premier spawn, reprise et réveil
    partagent exactement la même configuration (donc le même préfixe de cache)."""
    return [*_bouzecode_launch_cmd(), "-p", "--accept-all", "--loud"]


def _spawn_env(**extra: str) -> dict:
    """Env des agents spawnés : le package bouzecode du serveur doit gagner quel que
    soit le cwd (avec -P, le cwd sort de sys.path ; PYTHONPATH garantit la résolution).

    ⚠️ Les indices `parents[N]` sont comptés depuis CE fichier,
    `src/bouzecode/web_v2/runtime/runner/agent_commande.py` : `parents[4]` = `src`. Chaque
    déplacement du fichier les décale d'un cran (`web_v2/` → `runtime/`, puis `runtime/runner/`) ;
    un oubli faisait pointer PYTHONPATH DANS le package (`src/bouzecode`) au lieu de `src` —
    `import bouzecode` ne résolvait plus depuis la racine du serveur, ce qui est exactement la
    garantie anti-shadowing que cette fonction existe pour tenir."""
    pkg_root = str(Path(__file__).resolve().parents[4])
    previous = os.environ.get("PYTHONPATH", "")
    pythonpath = os.pathsep.join([pkg_root] + ([previous] if previous else []))
    return {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": pythonpath,
        **extra,
    }


def _brief_humain(agent: "Agent") -> bool:
    """Le parent de cet agent est PRÉVENU sans le piloter : tâche du Bureau rattachée à
    l'assistant qui l'a lancée (`dispatch.NON_MANAGE` sur son ticket). Son prompt est la tâche
    de l'humain, pas le brief d'un parent : les garde-fous d'un agent délégué (porte des
    parcours d'interface) ne s'appliquent pas. Relu sur le ticket à chaque (re)spawn ; un store
    illisible ne bloque pas le lancement (comportement de sous-agent, comme avant)."""
    if not (agent.ticket_slug and agent.ticket_id):
        return False
    try:
        from ...services.work import dispatch, tickets  # local : `dispatch` importe ce module
        ticket = tickets.get_ticket(agent.ticket_slug, agent.ticket_id)
    except Exception:  # noqa: BLE001 — loggé, le spawn a lieu
        logging.getLogger(__name__).exception("ticket de %s illisible", agent.agent_id)
        return False
    return bool(ticket) and not dispatch.est_manage(ticket)


def _ticket_env(agent: "Agent") -> dict:
    """Env carrying the agent's ticket identity + run kind, so its on_completion
    hook can POST /internal/runs/<agent_id>/ended. Rebuilt on every (re)spawn
    from the persisted Agent fields — survives continue_agent."""
    env: dict[str, str] = {"BOUZECODE_RUN_KIND": agent.run_kind or "work"}
    # Parenté : un SOUS-AGENT ne doit pas rester chaud. Le quart d'heure de résidence existe
    # pour laisser à l'UTILISATEUR le temps de revenir sur sa conversation ; un sous-agent
    # n'a pas d'utilisateur. Le process ne connaissait pas sa parenté (seul le serveur la
    # connaît), donc `_web_keep_warm` gardait TOUT le monde résident, y compris les douze
    # sous-agents d'un manager.
    #
    # ⚠️ `MANUAL_PARENT` N'EST PAS UNE PARENTÉ : c'est le sentinelle « lancé à la main depuis
    # l'UI ». Le poser ici éteignait le warm-pool pour les SEULES conversations qu'il existe
    # pour servir. Constat du 2026-08-03 sur le parc réel : 54 conversations utilisateur,
    # 54 process morts, 0 warm — donc respawn à froid à CHAQUE message ET à chaque follow-up,
    # là où la TUI garde son process entre les tours. C'est l'écart que l'utilisateur ressent.
    if agent.parent and agent.parent != MANUAL_PARENT:
        env["BOUZECODE_PARENT"] = agent.parent
        if _brief_humain(agent):
            env["BOUZECODE_BRIEF_HUMAIN"] = "1"
    # Profondeur dans l'arbre des sous-agents : l'outil `Agent` de l'enfant borne la récursion
    # dessus (config.max_agent_depth). Recalculée à chaque (re)spawn depuis la chaîne des parents.
    from ...services.work import profondeur  # local : le service relit les fiches du runner
    env["BOUZECODE_AGENT_DEPTH"] = str(profondeur.profondeur_agent(agent))
    if agent.ticket_slug:
        env["BOUZECODE_TICKET_SLUG"] = agent.ticket_slug
    if agent.ticket_id:
        env["BOUZECODE_TICKET_ID"] = agent.ticket_id
    if agent.ticket_id and agent.run_token:
        env["BOUZECODE_RUN_TOKEN"] = agent.run_token
    if agent.worktree_root:
        env["BOUZECODE_WORKTREE_ROOT"] = agent.worktree_root
    # Venv du dépôt de base : c'est ce qui empêche un worktree SANS venv demandé d'en voir un
    # apparaître (uv crée `./.venv` au premier `uv run`). Rejoué ici, donc valable aussi pour
    # tout respawn/continue, pas seulement au premier lancement.
    env.update(venv_env.base_venv_env(agent.base_venv))
    return env


class MissingProviderEnvError(RuntimeError):
    """Raised when required provider env vars are missing at agent spawn time."""


def _required_env_for_model(model: str) -> list[str]:
    """Return list of env var names required for the given model's provider."""
    from ....backend.agent.providers.registry import PROVIDERS
    for _name, prov in PROVIDERS.items():
        if model in prov.get("models", []):
            keys = [prov["api_key_env"]]
            # Anthropic always needs ANTHROPIC_BASE_URL at runtime (internal LLM gateway)
            if prov["type"] == "anthropic":
                keys.append("ANTHROPIC_BASE_URL")
            return keys
    # Unknown model — require at least one provider key
    return []


def check_provider_env(model: str, env: dict | None = None) -> None:
    """Raise MissingProviderEnvError if required env vars are absent."""
    env = env if env is not None else os.environ
    required = _required_env_for_model(model)
    missing = [k for k in required if not env.get(k)]
    if missing:
        raise MissingProviderEnvError(
            f"Variables d'environnement manquantes pour le modèle '{model}': {', '.join(missing)}. "
            "Vérifiez que le wrapper d'env corporate est actif."
        )


def _server_bouzecode_dir() -> Path:
    """`.bouzecode/` du repo serveur (profils transversaux : monitor/review/...).
    Passé en --extra-dir au spawn pour que les profils se résolvent quel que soit
    le cwd de l'agent (un projet cible n'a pas forcément de profils locaux).

    Même décompte que `_spawn_env` : depuis `runtime/runner/`, la racine du dépôt est
    `parents[5]`. Un cran de moins rendait `src/.bouzecode`, qui n'existe pas — l'`--extra-dir`
    ne désignait rien et les profils transversaux ne se résolvaient plus, en silence."""
    return bouzecode_project_dir(Path(__file__).resolve().parents[5])


def _profile_launch_args(profile: str) -> list[str]:
    """Re-inject a resumed agent's `--profile` (and the server extra-dir that carries
    its catalog). WITHOUT this, every resume/respawn boots with NO profile, so
    apply_profile_tools/hooks/skills/plan_mode never run: a read-only manager silently
    regains Edit/Write and starts CODING instead of dispatching. The persona survives
    (loaded from the resumed session) but the TOOL WHITELIST does not — hence the fix."""
    if not profile:
        return []
    args = ["--profile", profile]
    server_dir = _server_bouzecode_dir()
    if server_dir.is_dir():
        args += ["--extra-dir", str(server_dir)]
    return args
