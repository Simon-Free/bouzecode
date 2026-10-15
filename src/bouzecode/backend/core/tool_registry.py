# [desc] Central registry for tool plugins with thread-local overlays for concurrent Focus conversations. [/desc]
"""Tool plugin registry for bouzecode.

Provides a central registry for tool definitions, lookup, schema export,
and dispatch with output truncation.  Supports thread-local overlays so
concurrent Focus conversations each get an isolated view.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolDef:
    """Definition of a single tool plugin.

    Attributes:
        name: unique tool identifier
        schema: JSON-schema dict sent to the API (name, description, input_schema)
        func: callable(params: dict, config: dict) -> str
        read_only: True if the tool never mutates state
        concurrent_safe: True if safe to run in parallel with other tools
        ends_turn: True if a turn containing only this tool should NOT trigger a
            follow-up LLM cycle — the tool result is self-contained and the
            model has nothing meaningful to add afterwards.
        snippetable: True if this tool's result should be wrapped on the wire with
            snippet markers (see snippet_wire.py) so the model can freeze useful
            line ranges via Snippet(...).
        snippet_key: which identifier the model passes to Snippet — "tool_id"
            (default) or "file" (file_path-keyed).
        etat_externe: le résultat dépend d'un état tenu HORS de ce process (autres
            agents, serveur) : il peut changer sans que CET agent n'écrive rien, donc un
            appel identique n'est jamais servi depuis la mémoire anti-répétition.
        lot_simultane: outil NON concurrent_safe (il reste à sa place dans la file
            séquentielle, après un `Bash` qui le précède) dont les appels CONSÉCUTIFS d'un
            même lot partent ensemble — ex. `Agent` : N enfants indépendants démarrent
            d'un coup au lieu d'attendre chacun la fin du précédent.
    """
    name: str
    schema: Dict[str, Any]
    func: Callable[[Dict[str, Any], Dict[str, Any]], str]
    read_only: bool = False
    concurrent_safe: bool = False
    ends_turn: bool = False
    snippetable: bool = False
    snippet_key: Optional[str] = None
    etat_externe: bool = False
    lot_simultane: bool = False
    #  Outil qui n'a de sens que sous bouzeui web (flotte de tickets gouvernés) : hors web il
    #  n'est pas proposé au modèle (session 9d81964e : Fleet et MessageAgent appelés pour rien).
    web_seulement: bool = False


# --------------- framework vs work tools ---------------

# Framework tools are ALWAYS available to every agent, independent of any
# profile `tools` whitelist: they carry the methodology/discipline, skills,
# planning, diffing and final-answer machinery the harness relies on. A
# profile's `tools` list only ever whitelists the *work* tools (Read/Write/
# Edit/Bash/Glob/Grep/Agent/…); it can never strip these.
# FindCode/Tree (code navigation) belong here: LoadProjectConfig, which every agent
# has, points at them, and a profile whitelist must never strip the way to locate
# code. Both are deterministic and strictly read-only (no LLM, no file written).
# ImageQuestion, pour la même raison : le schéma de Read (outil de tous les profils) et le
# résultat d'une capture renvoient vers lui — une image n'entre plus jamais dans un résultat.
FRAMEWORK_ALWAYS_ON = frozenset({
    "Methodology", "Snippet", "FinalAnswer", "Skill", "SkillResearch",
    "TaskList", "GetDiff", "WritePlan", "LoadProjectConfig", "AskUserQuestion",
    "FindCode", "Tree", "ImageQuestion",
    #  Remontee NON bloquante d'un probleme (pendant d'AskUserQuestion) : tout agent, a toute
    #  profondeur, doit pouvoir prevenir l'humain sans s'arreter (tools/signaler.py).
    "Signaler",
    #  Nettoyage du contexte quand la tache change (context_manager/context_reset.py) :
    #  pendant de Methodology, tout agent doit pouvoir archiver sa note.
    "ResetContext",
    #  La TODO des chantiers du projet du ticket (tools/taches_projet.py) : tout agent doit
    #  pouvoir voir et CLASSER (faite/doublon/caduque) ce qu'il vient de resoudre. Creer,
    #  lancer, etc. restent a l'outil `Taches` du Bureau.
    "TachesProjet",
})


# --------------- process-level deny list ---------------

# Profil SERVEUR : quand bouzecode tourne pour une application hébergée (Demo),
# aucun outil ne doit sortir sur Internet ni exécuter de commande, QUEL QUE SOIT le
# profil d'agent chargé (un profil introuvable ou à `tools: []` rend TOUS les outils).
# `BOUZECODE_SERVER_PROFILE=1` interdit la liste ci-dessous ; `BOUZECODE_DENIED_TOOLS`
# (noms séparés par des virgules, motifs fnmatch acceptés : `mcp__*`) en ajoute.
# Un outil interdit n'est ni annoncé au modèle, ni exécutable, ni réactivable par
# `enable_tool()` : l'interdiction est relue dans l'environnement à chaque appel.
from .server_profile import SERVER_PROFILE_ENV, server_profile_active  # noqa: E402

DENIED_TOOLS_ENV = "BOUZECODE_DENIED_TOOLS"
SERVER_DENIED_TOOLS = (
    # Internet
    "WebFetch", "WebSearch", "EnableChromeDevtools", "mcp__*",
    "Mails", "Teams", "Canaux", "Brouillon", "Creneau", "Reunion",
    # Exécution de commandes / de code
    "Bash", "BashOutput", "RunPythonTest", "TestStatus", "Environment",
)


def denied_tool_patterns() -> tuple:
    """Motifs des outils interdits à ce process (profil serveur + liste explicite)."""
    patterns = []
    if server_profile_active():
        patterns.extend(SERVER_DENIED_TOOLS)
    extra = os.environ.get(DENIED_TOOLS_ENV) or ""
    patterns.extend(p.strip() for p in extra.split(",") if p.strip())
    return tuple(patterns)


def is_denied(name: str) -> bool:
    """True si `name` est interdit au niveau du process."""
    return any(fnmatchcase(name, pattern) for pattern in denied_tool_patterns())


def denied_tool_message(name: str) -> str:
    return (
        f"Error: l'outil `{name}` est interdit sur ce serveur ({SERVER_PROFILE_ENV} / "
        f"{DENIED_TOOLS_ENV}) : ni accès Internet ni exécution de commande. N'insiste pas, "
        "rappeler cet outil échouera à l'identique ; poursuis avec tes autres outils ou "
        "clôture par FinalAnswer en signalant le manque."
    )


# Écrire sous un `.bouzecode/` (plugins.json, plugins/, profiles/ à `requires_plugins`,
# skills) revient à faire charger du code au process par un chemin détourné : Write +
# Agent(subagent_type=...) ou LoadProjectConfig importaient ce code. En profil serveur,
# les outils d'écriture de fichiers y sont refusés, quel que soit le chemin donné.
SERVER_PROTECTED_WRITE_TOOLS = frozenset({"Write", "Edit", "NotebookEdit", "MultiEdit"})
_PATH_PARAMS = ("file_path", "notebook_path", "path")


def _touches_bouzecode_dir(raw: str) -> bool:
    candidates = {raw, os.path.abspath(raw)}
    try:
        candidates.add(os.path.realpath(raw))
    except (OSError, ValueError):
        pass
    for candidate in candidates:
        parts = candidate.replace("\\", "/").lower().split("/")
        if ".bouzecode" in parts or ".bouzecode" in parts:
            return True
    return False


def server_write_refusal(name: str, params: Dict[str, Any]) -> Optional[str]:
    """Refus explicite si, en profil serveur, `name` écrit sous un répertoire `.bouzecode/`."""
    if name not in SERVER_PROTECTED_WRITE_TOOLS or not server_profile_active():
        return None
    for key in _PATH_PARAMS:
        value = params.get(key)
        if isinstance(value, str) and value.strip() and _touches_bouzecode_dir(value.strip()):
            return (
                f"Error: `{name}` refusé sur ce serveur ({SERVER_PROFILE_ENV}) : écrire sous un "
                "répertoire `.bouzecode/` (plugins, profils, skills) ferait charger du code au "
                "process. N'insiste pas ; écris ailleurs ou clôture par FinalAnswer."
            )
    return None


# --------------- internal state ---------------

_registry: Dict[str, ToolDef] = {}
_disabled: set = set()  # tool names currently disabled

# Thread-local overlay for Focus conversations running in parallel
_local = threading.local()


def _has_overlay() -> bool:
    """Return True if the current thread has an active local overlay."""
    return getattr(_local, "active", False)


def _local_registry() -> Dict[str, ToolDef]:
    return getattr(_local, "registry", {})


def _local_disabled() -> set:
    return getattr(_local, "disabled", set())


# --------------- overlay lifecycle ---------------

def push_local_overlay() -> None:
    """Activate a thread-local overlay.

    While active, register/disable/enable operate on the local state,
    and lookups check local first then fall through to global.

    Le registre GLOBAL est peuplé AVANT d'activer l'overlay, et ce n'est pas une commodité.
    `registration` enregistre les 35 outils du gateway par EFFET DE BORD à l'import ; si cet
    import a lieu overlay actif, ils tombent dans `_local.registry` et `pop_local_overlay()`
    les JETTE. Le module restant dans `sys.modules`, plus aucun ré-import ne repeuple le
    global : il garde définitivement les seuls outils enregistrés hors overlay. Mesuré le
    2026-07-29 — 7 outils sur 42, `get_tool("Read")` rendant `None` pour toute la vie du
    processus, et `scope_guard` dénonçant `Read, Glob, Grep` comme outils d'écriture.
    """
    import bouzecode.backend.tools.registration  # noqa: F401 — peuple le registre GLOBAL
    _local.active = True
    _local.registry = {}
    _local.disabled = set()


def pop_local_overlay() -> None:
    """Deactivate the thread-local overlay, discarding local state."""
    _local.active = False
    _local.registry = {}
    _local.disabled = set()


# --------------- public API ---------------

def register_tool(tool_def: ToolDef) -> None:
    """Register a tool, overwriting any existing tool with the same name."""
    if _has_overlay():
        _local.registry[tool_def.name] = tool_def
    else:
        _registry[tool_def.name] = tool_def


def get_tool(name: str) -> Optional[ToolDef]:
    """Look up a tool by name. Returns None if not found."""
    if _has_overlay():
        local = _local_registry().get(name)
        if local is not None:
            return local
    return _registry.get(name)


def get_all_tools() -> List[ToolDef]:
    """Return all registered tools (insertion order)."""
    if _has_overlay():
        merged = dict(_registry)
        merged.update(_local_registry())
        return list(merged.values())
    return list(_registry.values())


# Scheduling properties injected into every tool schema. TYPE ONLY: leur sens est expliqué
# UNE fois dans le noyau (« # Un tour ») — répété dans chacun des ~40 schémas, il coûtait
# ≈ 90 tokens par outil et par appel (audit du 2026-09-24). Le DAG (`agent/dag.py`) et
# `execute_tool` les lisent/retirent sur n'importe quel outil, déclarés ou non.
_SCHEDULING_PROPS: Dict[str, Any] = {
    "depends_on": {"type": "array", "items": {"type": "string"}},
    "tool_call_alias": {"type": "string"},
}


def _coerce_params(params: Dict[str, Any], schema: Dict[str, Any]) -> None:
    """Best-effort type coercion of tool params to match declared schema types.

    Mutates *params* in place.  Currently handles:
    - string→int / string→float for numeric properties
    - string→bool for boolean properties
    - string→list for array properties (tries JSON parse)
    - int/float→string for string properties
    """
    props = schema.get("input_schema", {}).get("properties", {})
    for key, value in list(params.items()):
        prop_schema = props.get(key)
        if not prop_schema:
            continue
        declared_type = prop_schema.get("type")
        if declared_type == "integer" and isinstance(value, str):
            try:
                params[key] = int(value)
            except ValueError:
                raise ValueError(f"Parameter '{key}' expects integer, got '{value}'")
        elif declared_type == "number" and isinstance(value, str):
            try:
                params[key] = float(value)
            except ValueError:
                raise ValueError(f"Parameter '{key}' expects number, got '{value}'")
        elif declared_type == "boolean" and isinstance(value, str):
            if value.lower() in ("true", "1", "yes"):
                params[key] = True
            elif value.lower() in ("false", "0", "no"):
                params[key] = False
            else:
                raise ValueError(f"Parameter '{key}' expects boolean, got '{value}'")
        elif declared_type == "array" and isinstance(value, str):
            import json
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    params[key] = parsed
            except json.JSONDecodeError:
                pass
        elif declared_type == "string" and isinstance(value, (int, float)):
            params[key] = str(value)


TOOL_GATE_KEY = "_tool_gate"


def run_tool_gate(name: str, params: Dict[str, Any], config: Dict[str, Any]) -> Optional[str]:
    """Hook pré-exécution fourni par l'application hôte.

    `config["_tool_gate"]` : callable `(name, params, config) -> None | str`. None autorise
    l'appel ; une chaîne le REFUSE et devient le résultat rendu au modèle (l'outil n'est
    pas exécuté). Le hook peut aussi lever une exception : l'appel est alors refusé
    (échec FERMÉ) avec un message explicite. Clé préfixée `_` : jamais persistée par
    `save_config`. Sans hook, rien ne change.
    """
    gate = (config or {}).get(TOOL_GATE_KEY)
    if gate is None:
        return None
    import logging

    log = logging.getLogger(__name__)
    try:
        verdict = gate(name, params, config)
    except Exception as exc:  # noqa: BLE001 — échec fermé
        log.warning("tool_gate: %s refusé (erreur du point de contrôle : %s)", name, type(exc).__name__)
        # Le détail de l'exception (règles, chemins, identifiants de la politique) reste
        # dans le journal serveur : le modèle, ou une injection, n'en voit que le type.
        log.debug("tool_gate: détail de l'erreur pour %s", name, exc_info=True)
        return (f"Error: appel de `{name}` refusé par le point de contrôle des outils "
                f"(erreur du contrôle : {type(exc).__name__}).")
    if verdict is None:
        return None
    log.info("tool_gate: %s refusé", name)
    message = str(verdict).strip() or "refusé par le point de contrôle des outils"
    return message if message.startswith("Error") else f"Error: appel de `{name}` refusé : {message}"


# Clés privées (`_…`) qui DOIVENT suivre dans la config d'un sous-agent : les appels de
# config enfants filtrent les clés `_`, ce qui retirait le point de contrôle de l'hôte à
# tout sous-agent (Agent, relecteur de clôture).
INHERITED_PRIVATE_KEYS = (TOOL_GATE_KEY,)


def inherit_private(parent: Dict[str, Any], child: Dict[str, Any]) -> Dict[str, Any]:
    """Recopie dans `child` les clés privées à hériter (dont `_tool_gate`) ; rend `child`."""
    for key in INHERITED_PRIVATE_KEYS:
        if (parent or {}).get(key) is not None:
            child[key] = parent[key]
    return child


#  Flotte d'agents pilotable (Fleet, MessageAgent) : sous bouzeui web (tickets gouvernes) OU
#  dans un TUI interactif qui heberge ses sous-agents en process (backend/multi_agent/en_process).
_flotte_locale = False


def activer_flotte_locale(active: bool = True) -> None:
    """Le REPL interactif l'active : ses sous-agents en process forment une flotte."""
    global _flotte_locale
    _flotte_locale = active


def flotte_disponible() -> bool:
    """Les outils `web_seulement` ont-ils une flotte a piloter dans ce process ?"""
    return _flotte_locale or bool(os.environ.get("BOUZECODE_WEB_IPC_DIR"))


def get_tool_schemas() -> List[Dict[str, Any]]:
    """Return the schemas of all registered tools (for API tool parameter).

    Automatically injects the optional ``depends_on`` property into every
    tool's input_schema so the LLM can express dependency trees.
    """
    import copy

    if _has_overlay():
        disabled = _local_disabled()
        merged = dict(_registry)
        merged.update(_local_registry())
        tools_iter = merged.values()
    else:
        disabled = _disabled
        tools_iter = _registry.values()

    hors_web = not flotte_disponible()
    schemas = []
    for t in tools_iter:
        if t.name in disabled or is_denied(t.name) or (hors_web and t.web_seulement):
            continue
        s = copy.deepcopy(t.schema)
        props = s.get("input_schema", {}).get("properties")
        if props is not None and "depends_on" not in props:
            props.update(_SCHEDULING_PROPS)
        schemas.append(s)
    return schemas


def _memorisable(tool) -> bool:
    """Un appel identique peut-il être servi depuis la mémoire anti-répétition ?"""
    return getattr(tool, "read_only", False) and not getattr(tool, "etat_externe", False)


def _parametres_vides(name: str, names: str, config: Dict[str, Any]) -> str:
    """Erreur rendue au modèle pour un paramètre requis vide. Le conseil CDATA ne vaut que pour
    le protocole XML : en function-calling natif, MiMo (xiaomi/fp8) rend parfois `{}` quand une
    valeur contient du balisage — l'inviter à y mettre du CDATA aggravait le problème."""
    from ..agent.providers.registry import model_uses_native_tools

    tete = f"Error: required parameter(s) for {name} arrived empty or missing: {names}. "
    if model_uses_native_tools(str(config.get("model") or ""), config):
        return tete + (
            "The function call arrived with empty arguments. The call was NOT executed. "
            f"Please re-emit {name} with every required parameter filled, as plain JSON "
            "string values: no XML tags and no <![CDATA[...]]> wrapper inside the arguments."
        )
    return tete + (
        "This usually means the value was truncated during serialization — most "
        "often because the value contained raw quotes (\") or angle brackets and "
        "was not wrapped in <![CDATA[...]]>. The call was NOT executed. "
        f"Please re-emit {name} with the parameter(s) filled. "
        "Wrap values containing <, >, & or \" in <![CDATA[...]]>."
    )


def execute_tool(
    name: str,
    params: Dict[str, Any],
    config: Dict[str, Any],
    max_output: int = 120000,
) -> str:
    """Dispatch a tool call by name.

    Args:
        name: tool name
        params: tool input parameters dict
        config: runtime configuration dict
        max_output: maximum allowed output length in characters. Ignored for
            snippetable tools (see below).

    Returns:
        Tool result string, possibly truncated. Snippetable tools are never
        truncated here — the snippet wire owns large results.
    """
    # Strip scheduling hints — not actual tool parameters
    params.pop("depends_on", None)
    params.pop("tool_call_alias", None)

    if name == "_InvalidToolName":
        corrupted = params.get("_corrupted_name", "<unknown>")
        return (
            f"ERROR: the tool name {corrupted!r} is malformed (must match [a-zA-Z0-9_-]+). "
            "This usually means an upstream proxy mangled your tool call. "
            "Please re-emit the same tool call with a clean name "
            "(e.g. 'Write', 'Edit', 'Glob') and identical input parameters; do not retry verbatim."
        )

    if name == "_XmlParseError":
        diagnostic = params.get("_error", "unknown XML parse error")
        source = params.get("_source", "")
        return (
            f"ERROR parsing your tool call XML: {diagnostic}\n"
            f"Offending source: {source!r}\n"
            "Please re-emit the tool call with correctly-formed XML: "
            "<tool_use name=\"...\" id=\"...\"><param name=\"...\">value</param></tool_use>. "
            "Wrap values containing <, > or & in <![CDATA[...]]>."
        )

    # Check disabled — use overlay if active, else global
    if _has_overlay():
        disabled = _local_disabled()
    else:
        disabled = _disabled

    # A refusal must be TERMINAL: the agent cannot enable a tool itself, so the old
    # "Use /tools enable X" (a REPL command it cannot emit) bought 44 measured
    # relaunches of the very same refused call. The replacement names substitutes
    # taken from the registry this agent really has.
    from .tool_mentions import unavailable_tool_message

    if is_denied(name):
        return denied_tool_message(name)

    if name in disabled:
        return unavailable_tool_message(name, available_tool_names())

    tool = get_tool(name)
    if tool is None:
        return unavailable_tool_message(name, available_tool_names(), missing=True)

    valid_params = set((tool.schema.get("input_schema", {}).get("properties") or {}).keys())
    if valid_params:
        unknown = [k for k in params if k not in valid_params]
        if unknown:
            return (
                f"Error: unknown parameter(s) for {name}: {', '.join(unknown)}. "
                f"Valid parameters: {', '.join(sorted(valid_params))}."
            )

    # Guard against required params that arrived empty/blank. This is the
    # classic symptom of a serialization mishap (e.g. a param body truncated
    # because the model emitted raw quotes instead of wrapping the value in
    # CDATA): the param key exists but its value is "" or whitespace. Executing
    # anyway (e.g. Bash with command="") silently runs a no-op that lists the
    # cwd — a plausible-looking result that traps the model in a retry loop.
    # Refuse to execute and return an explicit, self-correcting message.
    required = (tool.schema.get("input_schema", {}) or {}).get("required", []) or []
    blank_required = [
        r for r in required
        if r not in params
        or (isinstance(params[r], str) and not params[r].strip())
    ]
    if blank_required:
        return _parametres_vides(name, ", ".join(blank_required), config)

    try:
        _coerce_params(params, tool.schema)
    except ValueError as e:
        valid = ', '.join(sorted(valid_params)) if valid_params else "(none)"
        return f"Error: invalid parameter format for {name}: {e}. Valid parameters: {valid}."

    refus = server_write_refusal(name, params)
    if refus is not None:
        return refus

    # Point de contrôle de l'hôte, APRÈS validation/coercition des paramètres et
    # AVANT la mémoire anti-répétition : un résultat mémorisé ne doit pas le contourner.
    refus = run_tool_gate(name, params, config)
    if refus is not None:
        return refus

    # Rejouer un appel de LECTURE à l'identique alors que rien n'a été écrit entre-temps
    # ne peut pas donner un autre résultat. On sert la mémoire, préfixée d'un rappel :
    # une session observée a joué trois fois le même WebFetch pour recevoir trois fois la
    # même page de login, sans jamais que rien ne lui dise qu'elle tournait en rond.
    from . import repeat_guard

    #  Sauf si le résultat dépend d'un état tenu ailleurs : un enfant qui finit, un serveur qui
    #  change, n'écrivent rien dans CE process. Essai 3 (2026-09-24) : une FinalAnswer refusée
    #  pour « enfant encore actif », rappelée à l'identique APRÈS l'avoir attendu, recevait la
    #  mémoire de son refus.
    reusable = _memorisable(tool)
    if reusable:
        memo = repeat_guard.recall(config, name, params)
        if memo is not None:
            return memo

    try:
        # Sous-agent en process : son dossier et ses variables, pas ceux du process (dossier_agent).
        from .dossier_agent import dans
        with dans((config or {}).get("_atelier")):
            result = tool.func(params, config)
    except Exception as e:
        from bouzecode.backend.tools.interaction import PausedForInput, DeferredChecks
        from bouzecode.backend.tools.plan_mode import PlanRejected
        if isinstance(e, (PausedForInput, DeferredChecks, PlanRejected)):
            raise
        return f"Error executing {name}: {e}"

    #  Cette frontiere est annotee `-> str` et TOUT l'aval la croit : `results: dict[str, str]`
    #  dans le DAG, `_compact_tool_result` qui passe le contenu tel quel, puis le `content`
    #  d'un message `role=tool` que l'API du modele exige en chaine. Or un outil metier peut
    #  rendre un dict (les huit outils du Bureau le font) : `len(dict)` comptant les CLES,
    #  il ne declenchait ni troncature ni exception et traversait en SILENCE jusqu'au fil,
    #  ou le tour mourait sans que l'assistant recoive ni resultat ni erreur. On serialise
    #  ICI, une fois, pour toute la classe des outils metier plutot que dans chaque wrapper.
    if not isinstance(result, str):
        import json

        try:
            result = json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            #  Un texte approximatif vaut mieux qu'un tour d'agent perdu en silence.
            result = str(result)

    if reusable:
        repeat_guard.remember(config, name, params, result)
    else:
        # Un outil qui n'est pas déclaré read_only a pu changer le disque, l'état git,
        # le réseau : plus rien ne garantit qu'un résultat mémorisé tient encore.
        repeat_guard.invalidate(config)

    # Snippetable tools are handled by the snippet wire (numbered lines,
    # destroyed-next-turn, model snippets the ranges it needs). Truncating here
    # would discard the MIDDLE of a large result before the model can snippet it
    # — exactly what broke get_br_content / get_br_generation_documentation on
    # >32 KB content (the variable-write rule lived in the truncated middle).
    if getattr(tool, "snippetable", False):
        return result

    # `max_tool_output` (config) était défini mais lu nulle part (rapport docs/reduction_tokens
    # §3.2) : un Read de 50 k car. ou une sortie MCP passaient entiers. Au-delà du plafond, la
    # sortie complète part dans un fichier et le résultat garde tête + queue + le chemin.
    max_output = int(config.get("max_tool_output", max_output))
    if len(result) > max_output:
        from ..tools.ops.truncation import truncate_tool_output
        sans_limite = 10 ** 9
        result = truncate_tool_output(result, name, max_lines=sans_limite, max_chars=max_output,
                                      head_lines=sans_limite, tail_lines=sans_limite)

    return result


def unregister_tool(name: str) -> None:
    """Remove a tool from the registry entirely."""
    if _has_overlay():
        _local_registry().pop(name, None)
        _local_disabled().discard(name)
    else:
        _registry.pop(name, None)
        _disabled.discard(name)


def disable_tool(name: str) -> None:
    """Disable a tool by name. Raises KeyError if tool not registered."""
    if _has_overlay():
        # In overlay mode, check both local and global for existence
        if name not in _local_registry() and name not in _registry:
            raise KeyError(f"Unknown tool: {name}")
        _local.disabled.add(name)
    else:
        if name not in _registry:
            raise KeyError(f"Unknown tool: {name}")
        _disabled.add(name)


def enable_tool(name: str) -> None:
    """Re-enable a previously disabled tool."""
    if _has_overlay():
        _local.disabled.discard(name)
    else:
        _disabled.discard(name)


def available_tool_names() -> List[str]:
    """Return the names this agent can actually call right now (registered AND enabled).

    This is the ground truth a refusal message must quote: anything else — a static
    list, a doc, a prompt — can drift out of the registry and prescribe a phantom.
    """
    return sorted(t.name for t in get_all_tools() if is_enabled(t.name))


def is_enabled(name: str) -> bool:
    """Return True if tool is not in the disabled set (nor denied to the process)."""
    if is_denied(name):
        return False
    if _has_overlay():
        return name not in _local_disabled()
    return name not in _disabled


def list_disabled() -> List[str]:
    """Return sorted list of disabled tool names."""
    if _has_overlay():
        return sorted(_local_disabled())
    return sorted(_disabled)


def reset_disabled() -> None:
    """Re-enable all tools."""
    if _has_overlay():
        _local.disabled.clear()
    else:
        _disabled.clear()


#  Outils que la liste blanche de `registration` coupe à l'import (outils Graph, outils hors
#  profil de code…). `reset_disabled()` les rallume TOUS : c'est ce que faisait `/agent default`
#  après `/assistant`, et un profil de code héritait alors de Mails/Teams/Reunion.
_disabled_par_defaut: set = set()


def figer_desactives_par_defaut() -> None:
    """Mémorise l'état « par défaut » (appelé à la fin de `registration`)."""
    _disabled_par_defaut.clear()
    _disabled_par_defaut.update(_disabled)


def restaurer_desactives_par_defaut() -> None:
    """Revient à l'état par défaut ; un outil enregistré après (plugin, MCP) reste allumé."""
    cible = _local.disabled if _has_overlay() else _disabled
    cible.clear()
    cible.update(_disabled_par_defaut)


def clear_registry() -> None:
    """Remove all registered tools. Intended for testing."""
    _registry.clear()
    _disabled.clear()
    if _has_overlay():
        _local.registry.clear()
        _local.disabled.clear()


def ends_turn(name: str) -> bool:
    """Return True if the named tool has ends_turn=True."""
    tool = get_tool(name)
    return tool.ends_turn if tool else False


def is_concurrent_safe(name: str) -> bool:
    """Return True if the named tool has concurrent_safe=True."""
    tool = get_tool(name)
    return tool.concurrent_safe if tool else False


def is_lot_simultane(name: str) -> bool:
    """True si les appels consécutifs de cet outil, dans un même lot, partent ensemble."""
    tool = get_tool(name)
    return tool.lot_simultane if tool else False
