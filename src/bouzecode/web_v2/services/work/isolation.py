# [desc] Le paramètre d'isolation d'un agent : 3 valeurs (shared / worktree / worktree+venv) + garde-fou anti-collision. [/desc]
"""Isolation demandée au spawn d'un agent — UNE valeur à trois états.

Depuis le retrait de la chaîne automatique, ce n'est plus une cascade de règles qui
devine l'environnement d'un agent : c'est le MANAGER (ou l'humain qui lance) qui le
demande, parce que lui seul sait s'il lance trois agents en parallèle sur le même
dépôt ou un seul qui va toucher `pyproject.toml`.

| Valeur           | Ce que ça provisionne              | Quand la choisir                        |
|------------------|------------------------------------|-----------------------------------------|
| `shared`         | rien (dépôt principal)             | lecture seule, seul écrivain, tâche courte |
| `worktree`       | worktree git dédié, SANS venv      | plusieurs agents écrivent en parallèle  |
| `worktree+venv`  | worktree git ET venv dédiés        | l'agent touche aux dépendances          |

Trois valeurs, pas deux booléens : le couple (pas de worktree, venv) n'a pas de sens
et n'a pas à être représentable. Séparer worktree et venv est le gain de latence
principal — un worktree git est quasi gratuit, un venv c'est un `uv sync` par agent.

GARDE-FOU : deux agents `shared` qui ÉCRIVENT dans le MÊME dépôt s'écrasent mutuellement.
C'est la seule façon vraiment destructrice de se tromper, donc le serveur la rattrape : le
second est basculé en `worktree` et un commentaire l'explique sur le ticket. Le
manager reste maître de tout le reste.

Un agent qui NE PEUT PAS écrire (profil sans outil mutant l'arbre — le `manager`
read-only, par ex.) ne compte PAS dans ce garde-fou : il n'écrase personne. Sans cette
distinction, tout enfant `shared` dispatché par un manager `shared` était relevé en
`worktree` — le manager perdait la maîtrise que ce module lui accorde, et un agent
d'inventaire rendait des chemins absolus pointant vers un worktree jetable."""
from __future__ import annotations

import os

from . import repos

SHARED = "shared"
WORKTREE = "worktree"
WORKTREE_VENV = "worktree+venv"
ISOLATION_MODES = (SHARED, WORKTREE, WORKTREE_VENV)

# `idle` (warm pool) EN FAIT PARTIE : le process est résident dans son worktree et y
# écrira dès qu'on lui pousse un followup. L'en retirer libérerait son arbre aux yeux
# de `agents_writing_in` → deux agents sur le même worktree (collision d'arbre partagé).
_ACTIVE_STATES = ("running", "starting", "awaiting_input", "awaiting_plan_validation", "idle")

# Outils qui MUTENT la flotte d'agents, jamais l'arbre de travail. Leur ToolDef porte
# `read_only=False` (ils ont bien un effet de bord : ils spawnent/pilotent des agents),
# mais aucun octet du dépôt n'en sort — un manager qui dispatche n'écrase aucun fichier.
_FLEET_TOOLS = frozenset({"Agent", "MessageAgent", "Fleet"})

_COLLISION_COMMENT = (
    "🔀 Isolation relevée de « shared » à « worktree » : {count} agent(s) ÉCRIVAIN(S) "
    "travaillent déjà dans le dépôt principal ({agents}). Deux agents qui écrivent dans le "
    "même arbre de travail s'écrasent mutuellement, donc celui-ci reçoit son propre worktree "
    "git (sans venv). Les agents en LECTURE SEULE (manager…) ne sont pas comptés : ils "
    "n'écrasent personne. Pour l'éviter, demande explicitement `isolation=\"worktree\"`."
)


def _same_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _tool_writes_working_tree(name: str) -> bool:
    """Cet outil peut-il modifier des fichiers du dépôt ? Réponse tirée de la VRAIE source :
    le `read_only` déclaré sur le ToolDef enregistré (Read/Glob/Grep/… = True, Write/Edit/
    Bash = False), moins les outils de pilotage de flotte qui ne touchent aucun fichier.

    Prudence volontaire : un outil INCONNU du registre (plugin non chargé dans le process
    serveur) est compté comme écrivain — le garde-fou ne doit jamais s'effacer par ignorance."""
    if name in _FLEET_TOOLS:
        return False
    import bouzecode.backend.tools.registration  # noqa: F401 — peuple le registre
    from bouzecode.backend.core.tool_registry import get_tool
    tool = get_tool(name)
    return tool is None or not tool.read_only


def agent_can_write(agent) -> bool:
    """L'agent peut-il modifier l'arbre de travail ? Dérivé des outils RÉELLEMENT accordés.

    Un profil qui déclare une whitelist `tools:` NON VIDE la voit appliquée telle quelle par
    `ui.cli.apply_profile_tools` : tout outil de travail absent de la liste est `disable_tool`
    dans le process de l'agent (d'où les « Error: tool 'Write' is currently disabled » du
    manager). Cette whitelist est donc la source fiable — pas le nom de la typologie.

    Aucune whitelist (profil vide, absent, ou `tools: []`) = AUCUNE restriction : l'agent
    garde les outils de travail par défaut, Write/Edit/Bash compris → écrivain."""
    from bouzecode.backend.profiles import resolve_agent_profile
    name = (getattr(agent, "profile", "") or "").strip()
    profile = resolve_agent_profile(name) if name else None
    declared = list(getattr(profile, "tools", None) or []) if profile is not None else []
    if not declared:
        return True
    return any(_tool_writes_working_tree(tool) for tool in declared)


def agents_sharing_cwd(cwd: str) -> list[str]:
    """agent_ids des agents ENCORE ACTIFS **et capables d'écrire** dont le cwd est EXACTEMENT
    `cwd` (donc des agents `shared` sur ce dépôt : un agent isolé a pour cwd son worktree,
    jamais la racine du projet). Les agents read-only sont exclus — ils ne peuvent écraser
    le travail de personne, donc ils n'ont aucune raison de forcer un worktree à un voisin.
    Le filtre par chemin est fait AVANT toute lecture de session/profil — seuls les candidats
    réels coûtent une I/O."""
    from ...runtime import runner
    from ..sessions import store
    candidates = [a for a in runner.list_agents() if a.cwd and _same_path(a.cwd, cwd)]
    return [a.agent_id for a in candidates
            if store.agent_status(a)["state"] in _ACTIVE_STATES and agent_can_write(a)]


def resolve_isolation(project_path: str, requested: str,
                      needs_worktree: bool = False) -> tuple[str, str, str]:
    """Normalise l'isolation DEMANDÉE et applique le garde-fou anti-collision.

    Renvoie `(mode, raison, commentaire)` : `mode` ∈ ISOLATION_MODES, `raison` est une
    phrase pour les logs/l'API, `commentaire` est le texte à poster sur le ticket quand
    le serveur a corrigé la demande (vide sinon).

    Ordre : valeur inconnue → défaut `shared` ; projet non-git → `shared` forcé (aucun
    worktree possible) ; besoin structurel d'un worktree (éphémère, reprise de branche)
    → au moins `worktree` ; enfin le garde-fou de collision (qui ne compte QUE les agents
    capables d'écrire — cf. `agent_can_write`)."""
    mode = requested if requested in ISOLATION_MODES else SHARED
    if not repos.repo_root(project_path):
        raison = "pas un dépôt git : isolation impossible"
        if not needs_worktree:
            return SHARED, raison, ""
        # Le worktree n'était pas un confort mais une EXIGENCE (bac à sable éphémère,
        # reprise ou travail sur une branche précise). On dégrade quand même — refuser
        # le dispatch serait une décision produit — mais JAMAIS en silence : l'agent va
        # écrire dans l'arbre principal au lieu de la branche attendue, et livrer
        # ailleurs que là où on l'attend est le défaut le plus coûteux de la chaîne
        # parce qu'il ne se voit pas. Le commentaire remonte au ticket ET au manager.
        return SHARED, raison, (
            f"⚠️ ISOLATION EXIGÉE MAIS IMPOSSIBLE : {project_path} n'est pas un dépôt git. "
            f"Le ticket demandait un worktree (éphémère, reprise ou branche de travail) ; "
            f"l'agent travaillera dans l'ARBRE PRINCIPAL, sur la branche courante, et son "
            f"travail ne sera ni isolé ni jetable. Enregistre le projet comme dépôt git, ou "
            f"assume que ce ticket écrit en partagé."
        )
    if needs_worktree and mode == SHARED:
        return WORKTREE, "worktree exigé (ticket éphémère ou reprise de branche)", ""
    if mode != SHARED:
        return mode, f"isolation demandée : {mode}", ""
    busy = agents_sharing_cwd(project_path)
    if not busy:
        return SHARED, "shared (dépôt principal libre)", ""
    return (
        WORKTREE,
        f"garde-fou : {len(busy)} agent(s) shared ÉCRIVAIN(S) déjà actif(s) sur ce dépôt",
        _COLLISION_COMMENT.format(count=len(busy), agents=", ".join(sorted(busy))),
    )
