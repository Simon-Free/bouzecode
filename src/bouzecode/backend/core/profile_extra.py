# [desc] Resolves and caches per-profile system_prompt_extra, merging typology profiles with built-in capability fragments.
# 
# Resolves and caches per-profile system_prompt_extra, merging typology profiles with built-in capability fragments. [/desc]
from bouzecode.paths import project_dir as bouzecode_project_dir
import platform
import re
from pathlib import Path


_DEFAULT_PROFILE_EXTRA_CACHE: dict[str, str] = {}

# Always-on capability fragments shipped with bouzecode, composed into every
# depth-0 agent prompt regardless of the cwd project's own profiles.
_BUILTIN_CAPABILITIES = ["deferred"]

#  Suffixe du fichier de contexte PERSONNEL d'un profil. Demande utilisateur du 2026-09-21 :
#  « enrichir le system prompt de mon assistant Bureau pour mon usage perso, donc par user,
#  pas dans le code ». Les deux voies existantes ne convenaient pas :
#    - `~/.bouzecode/memory/*.md` s'applique à TOUS les agents de la machine, pas à un rôle ;
#    - `~/.bouzecode/profiles/<nom>.yaml` surcharge le profil PAR NOM, donc écraserait la prose
#      du rôle ET sa tool allowlist (`bureau-assistant` perdrait son « pas d'Edit/Write/Bash »).
#  D'où cette couche purement ADDITIVE : un simple markdown posé à côté des profils, nommé
#  d'après le profil qu'il enrichit (`bureau-assistant.local.md`), concaténé EN DERNIER.
_LOCAL_PROSE_SUFFIX = ".local.md"

#  Blocs de prose propres à une plateforme. Une consigne Windows (PowerShell, proxy NTLM,
#  chemins `C:\\`) envoyée à un agent Linux coûte des tokens à chaque appel ET l'invite à
#  écrire du PowerShell (audit du 2026-09-24). Syntaxe, lignes entières :
#      <!-- si:windows -->
#      ...consigne gardée seulement sous Windows...
#      <!-- /si -->
#  Le nom est celui de `platform.system()` en minuscules (windows, linux, darwin).
_PLATFORM_BLOCK_RE = re.compile(
    r"^[ \t]*<!-- si:(?P<plateforme>[a-z]+) -->[ \t]*\n(?P<corps>.*?)^[ \t]*<!-- /si -->[ \t]*(?:\n|\Z)",
    re.DOTALL | re.MULTILINE,
)


def filter_platform_blocks(text: str, system: str | None = None) -> str:
    """Garde le corps des blocs `<!-- si:<plateforme> -->` de la plateforme courante, retire les
    autres (balises comprises)."""
    if "<!-- si:" not in (text or ""):
        return text
    courant = (system or platform.system()).lower()
    #  `<!-- si:flotte -->` : prose qui prescrit Fleet / MessageAgent, gardée seulement quand
    #  ces outils sont proposés (web, ou TUI qui héberge ses sous-agents en process).
    from .tool_registry import flotte_disponible
    gardes = {courant, "flotte"} if flotte_disponible() else {courant}

    def _garde(m: re.Match) -> str:
        return m.group("corps") if m.group("plateforme") in gardes else ""

    return _PLATFORM_BLOCK_RE.sub(_garde, text)


def _load_local_prose(roots, profile_name: str) -> list[str]:
    """Prose personnelle de l'utilisateur pour ce profil, dans l'ordre des roots.

    Un fichier par root (`<root>/profiles/<profile_name>.local.md`) : le user-global
    (`~/.bouzecode`) apporte le contexte de la machine, le projet (`<cwd>/.bouzecode`) le
    contexte du dépôt, et les extra-dirs le reste — les trois s'ADDITIONNENT au lieu de se
    remplacer, puisqu'il ne s'agit pas d'un réglage mais de faits que l'agent ignore.

    Lu en `utf-8-sig` : édité à la main sous Windows (Notepad), le fichier porte un BOM qui
    sinon se retrouverait collé au premier titre du prompt.
    Un fichier absent, vide ou illisible est ignoré SANS erreur : du contexte de confort ne
    doit jamais empêcher un agent de démarrer.
    """
    blocs: list[str] = []
    for root in roots:
        chemin = Path(root) / "profiles" / f"{profile_name}{_LOCAL_PROSE_SUFFIX}"
        try:
            prose = chemin.read_text(encoding="utf-8-sig").strip()
        except OSError:
            continue
        if not prose:
            continue
        #  L'en-tête nomme la source : l'agent doit pouvoir dire « d'après ton contexte perso »
        #  et ne pas confondre ces faits avec les consignes de son rôle.
        blocs.append(f"# Contexte local (profil {profile_name})\n\n{prose}")
    return blocs


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
    from ..profiles.discovery import builtin_dir

    # 'autre'/empty map to 'default'; any other name resolves as-is
    profile_name = "default" if classification in ("", "autre", "default") else classification

    # CONFIG_DIR (~/.bouzecode) first so user-global profiles resolve here too —
    # otherwise `--profile <user-global-name>` silently runs without its prompt.
    roots = [CONFIG_DIR, bouzecode_project_dir(Path.cwd()), *get_extra_dirs()]
    from .tool_registry import flotte_disponible  # les blocs `si:flotte` changent la prose
    cache_key = (f"{profile_name}|flotte={flotte_disponible()}|"
                 + "|".join(str(r) for r in roots))
    if cache_key in _DEFAULT_PROFILE_EXTRA_CACHE:
        return _DEFAULT_PROFILE_EXTRA_CACHE[cache_key]
    # System builtins (meta-agent / manager / general-purpose) seed the set so
    # `--profile meta-agent` resolves; user/project/extra profiles override by name.
    available: dict = dict(load_system_profiles())
    # Le calque `default` est SHIPPÉ DANS LA WHEEL (`backend/profiles/builtin/default.yaml`)
    # pour s'appliquer à TOUS les projets, et pas seulement à ceux qui posent un
    # `.bouzecode/profiles/default.yaml` chez eux. `load_system_profiles()` ne le voit pas
    # (il ne garde que `kind: system`, réservé aux agents switchables), donc le dossier
    # builtin est chargé ici, en PLUS BASSE précédence : builtin < user-global < projet <
    # extra-dirs — le même ordre que `profile_search_dirs(include_builtin=True)`. Un projet
    # garde donc la possibilité de surcharger `default` par un fichier homonyme.
    available.update(load_profiles_from_dir(builtin_dir()))
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
    extra = filter_platform_blocks(extra).strip()

    #  Contexte PERSONNEL en DERNIER, après le rôle et les fragments builtin : sur une
    #  information contradictoire, c'est ce que l'utilisateur a écrit lui-même que le modèle
    #  lit en dernier. Purement prose : ce fichier n'accorde aucun outil (les allowlists sont
    #  résolues par `resolve_agent_profile` depuis le YAML nommé seul), donc enrichir le
    #  prompt de `bureau-assistant` ne peut pas lui rendre Edit/Write/Bash.
    prose_locale = _load_local_prose(roots, profile_name)
    if prose_locale:
        extra = "\n\n".join([extra, *prose_locale]).strip() if extra else "\n\n".join(prose_locale)

    _DEFAULT_PROFILE_EXTRA_CACHE[cache_key] = extra
    return extra
