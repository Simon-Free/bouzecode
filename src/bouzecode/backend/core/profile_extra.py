# [desc] Resolves and caches per-profile system_prompt_extra, merging typology profiles with built-in capability fragments.
# 
# Resolves and caches per-profile system_prompt_extra, merging typology profiles with built-in capability fragments. [/desc]
from pathlib import Path


_DEFAULT_PROFILE_EXTRA_CACHE: dict[str, str] = {}

# Always-on capability fragments shipped with bouzecode, composed into every
# depth-0 agent prompt regardless of the cwd project's own profiles.
_BUILTIN_CAPABILITIES = ["deferred"]


def _load_builtin_capabilities() -> list:
    """Load the always-on built-in capability fragment profiles (packaged with
    bouzecode under profiles/builtin/). Returns the AgentProfiles in declared
    order; missing fragments are skipped."""
    from ..profiles import load_profiles_from_dir
    import bouzecode.backend.profiles as _profiles_pkg

    builtin_dir = Path(_profiles_pkg.__file__).parent / "builtin"
    available = load_profiles_from_dir(builtin_dir)
    return [available[n] for n in _BUILTIN_CAPABILITIES if n in available]


def _inherits_default(profile) -> bool:
    """True when `profile` accepts the shared `default` prose layer underneath it.

    A profile that could not be resolved (an unclassified task type such as 'feature'
    or 'bug', which is NOT a profile name) inherits it too: the depth-0 agent is the
    code-development agent, so it must never run without the shared code layer."""
    return getattr(profile, "inherit_default", True) if profile is not None else True


def get_default_agent_profile_extra() -> str:
    """Return the `default` profile's system_prompt_extra (the code-agent layer).

    Resolved from .bouzecode/profiles in the cwd plus any registered extra dirs,
    cached per resolution root. Returns "" when no default profile is found.
    The dispatch layer appends this to the noyau for the top-level agent only.
    """
    return get_agent_profile_extra("default")


def get_agent_profile_extra(classification: str) -> str:
    """Return the composed system_prompt_extra for the given profile name.

    classification is either a task classification ('feature', 'bug', 'autre'/'default')
    or any explicit profile name (e.g. set via the --profile CLI flag).
    Resolved from the user-global ~/.bouzecode/profiles plus .bouzecode/profiles in
    the cwd plus any registered extra dirs (same precedence as the /agent switch:
    user-global < project < extra-dirs), cached per (classification, resolution
    root). Returns "" when profile is not found.

    COMPOSITION (prose only) — a named profile EXTENDS the shared layer, it never
    replaces it. The prompt layers are concatenated in this order:
      1. the `default` profile   — shared code-agent prose (discovery ladder, batching
         via `depends_on`, TDD, interdicts). Skipped when the named profile declares
         `inherit_default: false` (read-only roles such as `manager`).
      2. the named profile       — role-specific prose. It comes LAST of the two, so on
         a conflicting instruction the specialised layer is the one the model reads
         last and follows.
      3. builtin capability fragments (`deferred`) — always on.
    Tool allowlists, hooks, skills, plan_mode and require_recap are NOT composed here:
    they are resolved from the named profile ALONE (`resolve_agent_profile` →
    `apply_profile_tools`/`_skills`/`_hooks`), so composing prose can never re-grant a
    tool a restrictive profile deliberately removed.
    """
    from .config import CONFIG_DIR
    from .paths import get_extra_dirs
    from ..profiles import load_profiles_from_dir, merge_profiles, load_system_profiles

    # 'autre'/empty map to 'default'; any other name resolves as-is
    profile_name = "default" if classification in ("", "autre", "default") else classification

    # CONFIG_DIR (~/.bouzecode) first so user-global profiles resolve here too —
    # otherwise `--profile <user-global-name>` silently runs without its prompt.
    roots = [CONFIG_DIR, Path.cwd() / ".bouzecode", *get_extra_dirs()]
    cache_key = f"{profile_name}|" + "|".join(str(r) for r in roots)
    if cache_key in _DEFAULT_PROFILE_EXTRA_CACHE:
        return _DEFAULT_PROFILE_EXTRA_CACHE[cache_key]
    # System builtins (meta-agent / manager / general-purpose) seed the set so
    # `--profile meta-agent` resolves; user/project/extra profiles override by name.
    available: dict = dict(load_system_profiles())
    for root in roots:
        available.update(load_profiles_from_dir(root / "profiles"))
    profile = available.get(profile_name)

    # Composition (not inheritance): shared `default` layer, then the named profile,
    # then the always-on built-in capability fragments (shipped with bouzecode,
    # present in every project regardless of its own profiles).
    fragments = []
    base = available.get("default")
    if base is not None and profile_name != "default" and _inherits_default(profile):
        fragments.append(base)
    if profile:
        fragments.append(profile)
    fragments.extend(_load_builtin_capabilities())
    extra = merge_profiles(fragments).system_prompt_extra.strip() if fragments else ""
    _DEFAULT_PROFILE_EXTRA_CACHE[cache_key] = extra
    return extra
