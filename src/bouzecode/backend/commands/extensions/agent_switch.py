# [desc] /agent slash-command : liste les agents/profils spécialisés et bascule la session courante vers une typologie (system prompt + tools + model), en conservant le contexte variable (methodology/snippet). [/desc]
"""`/agent` (no arg) lists built agents/profiles + how to build more.
`/agent <name>` swaps the live session onto that typology; `/agent default` reverts."""
from __future__ import annotations

from bouzecode.ui.ansi import clr, info, ok, warn

from .agent_install import _catalog_split, _install

_HOOK_FLAGS = {
    "test_enforcement": "enforce_tests",
    "enforcement": "enforce_methodology",
    "loop_detection": "detect_loops",
    "lean_prompt": "lean_turn_protocol",
}
# Tools an agent always needs to run/close a turn, kept even outside its allowlist.
_ESSENTIAL_TOOLS = {"FinalAnswer", "Methodology", "Snippet", "AskUserQuestion"}
_REVERT_WORDS = {"default", "none", "off", "reset"}


def _head(profile) -> str:
    """One-line summary for listings: the description, else the prompt's first line."""
    text = (getattr(profile, "description", "") or profile.system_prompt_extra or "").strip()
    return text.split("\n", 1)[0][:60]


def _resolve_target(name: str):
    """Resolve *name* to a single AgentProfile from the unified set: system builtins
    (general-purpose / meta-agent / manager) plus user/project/catalog-installed profiles
    (the latter win on name collision). Returns None if unknown.

    Catalog-installed profiles already live on disk in ~/.bouzecode/profiles (written by
    `/agent install`), so no network is touched here. Composable fragments like `deferred`
    (kind: fragment) are excluded by load_system_profiles and are never switchable."""
    from bouzecode.backend.profiles import resolve_agent_profile
    return resolve_agent_profile(name)


def _apply(profile, config: dict) -> None:
    from bouzecode.backend.core.tool_registry import get_all_tools, reset_disabled, disable_tool

    if profile.model:
        config["model"] = profile.model
    config["require_recap"] = getattr(profile, "require_recap", False)
    for hook in profile.hooks:
        key = hook[3:] if hook.startswith("no-") else hook
        flag = _HOOK_FLAGS.get(key)
        if flag is not None:
            config[flag] = not hook.startswith("no-")

    reset_disabled()
    if profile.tools:
        keep = set(profile.tools) | _ESSENTIAL_TOOLS
        for tool in get_all_tools():
            if tool.name not in keep:
                disable_tool(tool.name)

    config["_agent_system_prompt_extra"] = profile.system_prompt_extra
    config["_profile_skills"] = list(profile.skills)
    config["_active_agent"] = profile.name


def _revert(config: dict) -> None:
    from bouzecode.backend.core.tool_registry import reset_disabled
    reset_disabled()
    config.pop("_agent_system_prompt_extra", None)
    config.pop("_profile_skills", None)
    config.pop("_active_agent", None)


def _print_section(title: str, profiles: dict, active, *, installable: bool = False) -> None:
    if not profiles:
        return
    print(clr(f"\n  {title} :", "cyan", "bold"))
    for name, p in sorted(profiles.items()):
        marker = clr("  ← actif", "green") if name == active else ""
        head = _head(p)
        print(clr(f"   {name:18s}", "yellow") + (clr(f"  {head}", "dim") if head else "") + marker)
    if installable:
        print(clr("   → installer : ", "dim") + "/agent install <nom>")


def _list(config: dict) -> None:
    from bouzecode.backend.profiles.discovery import load_system_profiles

    active = config.get("_active_agent")
    info(clr("  Agent actif : ", "cyan") + (active or "(aucun — agent par défaut)"))

    system = load_system_profiles()
    installed, available = _catalog_split()
    # A system agent shadowed by a same-named user profile is shown once, under système.
    installed = {n: p for n, p in installed.items() if n not in system}

    _print_section("Agents système", system, active)
    _print_section("Agents installés", installed, active)
    _print_section("Agents disponibles (catalogue partagé)", available, active, installable=True)

    print(clr("\n  Basculer : ", "cyan") + "/agent <nom>   |   revenir : /agent default")
    print(clr("  Construire/modifier un agent :", "cyan"))
    print("   - UI : lance le serveur web (bouzequi2), onglet « Agents » (tools/skills/hooks + prompt)")
    print("   - ou demande à l'agent méta : /agent meta-agent")


def cmd_agent(args: str, state, config) -> bool:
    """List specialized agents/profiles, or switch the session onto one."""
    name = args.strip()
    if not name:
        _list(config)
        return True

    sub, _, rest = name.partition(" ")
    if sub == "refresh":
        from bouzecode.backend.profiles import catalog
        try:
            catalog.refresh_catalog(force=True)
            ok("Catalogue d'agents partagés rafraîchi.")
        except Exception as exc:  # noqa: BLE001 — surface, don't crash
            warn(f"Échec du rafraîchissement du catalogue : {exc}")
        _list(config)
        return True

    if sub == "install":
        _install(rest.strip(), config)
        return True

    if name in _REVERT_WORDS:
        _revert(config)
        ok("Agent par défaut restauré (tous les tools réactivés, prompt de base).")
        return True

    profile = _resolve_target(name)
    if profile is None:
        warn(f"Agent/profil inconnu : {name}. Tape /agent pour la liste.")
        return True

    _apply(profile, config)
    # Le contexte variable (methodology/snippet dans state.context_state.notes) est conservé.
    bits = []
    if profile.tools:
        bits.append(f"{len(profile.tools)} tools")
    if profile.model:
        bits.append(f"modèle {profile.model}")
    suffix = f" ({', '.join(bits)})" if bits else ""
    ok(f"Basculé sur l'agent « {profile.name} »{suffix}. Contexte conservé ; le cache KV repart.")
    return True
