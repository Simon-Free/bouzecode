import os
import subprocess
from pathlib import Path
from datetime import datetime

from ._embedded_data import (
    SYSTEM_PROMPT_TEMPLATE,
    THINK_OUT_LOUD_PROMPT,
    WINDOWS_PLATFORM_HINTS,
    PLAN_MODE_TEMPLATE,
)


def checked_out_branch(cwd: str = "") -> str:
    """Branche RÉELLEMENT sortie dans `cwd` (défaut : le répertoire courant), "" hors dépôt.

    C'est la vérité terrain, celle que git rapporte — pas ce que le ticket AFFIRME. Un ticket
    peut dire « ta branche de travail = agent/X » alors que le worktree provisionné porte
    `agent/Y` : l'agent travaillait alors correctement au mauvais endroit et le rapportait de
    bonne foi. Le contrat de worktree cite désormais CE nom.

    `cwd` inexistant -> "" : `subprocess.run` LÈVE sur un cwd absent, et cet appel se fait
    depuis la construction du system prompt. Un BOUZECODE_WORKTREE_ROOT périmé (worktree
    moissonné puis rasé) tuait donc l'agent avant son premier tour, au lieu de le priver
    d'une seule phrase du contrat."""
    if cwd and not Path(cwd).is_dir():
        return ""
    result = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                            cwd=cwd or None, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    return result.stdout.strip() if result.returncode == 0 else ""


# Mémorisation par répertoire, dans CE process. `build_system_prompt` est rappelé (reprise,
# compaction, second tour) et repayait à chaque fois trois `git`. Volontairement sans
# expiration : la vie d'un agent est courte et son dépôt ne change pas sous ses pieds au point
# de fausser trois lignes de contexte. Un process neuf repart d'un cache vide.
_GIT_INFO_MEMO: dict[str, str] = {}


def _git_sortie(args: list[str]) -> str:
    """Sortie d'une commande git, "" si elle échoue. Ne lève jamais."""
    try:
        return subprocess.check_output(
            args, stderr=subprocess.DEVNULL, text=True,
            encoding="utf-8", errors="replace").strip()
    except Exception:  # noqa: BLE001 — une info de contexte absente ne doit pas tuer le boot
        return ""


def get_git_info() -> str:
    """Les trois lectures git du prompt système, EN PARALLÈLE.

    Mesuré le 2026-07-30 : ces trois `subprocess` coûtaient 0,50 s au démarrage de CHAQUE
    agent — 99,6 % du temps de `build_system_prompt` — et ils sont indépendants. Sous Windows
    un spawn de process est cher ; les mener de front ramène le coût à celui du plus lent,
    ~0,17 s. C'est autant de retiré aux ~4 s que l'utilisateur attend avant le premier signe
    de vie de son agent.
    """
    memo = _GIT_INFO_MEMO.get(os.getcwd())
    if memo is not None:
        return memo
    try:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=3) as pool:
            f_branch = pool.submit(checked_out_branch)
            f_status = pool.submit(_git_sortie, ["git", "status", "--short"])
            f_log = pool.submit(_git_sortie, ["git", "log", "--oneline", "-5"])
            branch, status, log = f_branch.result(), f_status.result(), f_log.result()
        parts = [f"- Git branch: {branch}"]
        if status:
            lines = status.split('\n')[:10]
            parts.append("- Git status:\n" + "\n".join(f"  {l}" for l in lines))
        if log:
            parts.append("- Recent commits:\n" + "\n".join(f"  {l}" for l in log.split('\n')))
        info = "\n".join(parts) + "\n"
    except Exception:  # noqa: BLE001 — hors dépôt git : contexte vide, jamais d'échec de boot
        info = ""
    _GIT_INFO_MEMO[os.getcwd()] = info
    return info





def get_platform_hints() -> str:
    """Return platform-specific shell hints. Windows-only for now; empty elsewhere."""
    import platform
    if platform.system() == "Windows":
        return WINDOWS_PLATFORM_HINTS
    return ""


def get_skills_section() -> str:
    """Return a short instruction telling the model to call SkillList()."""
    return """
# Skills

Skills are reusable knowledge templates (correct sequences, pitfalls, project patterns).
Call `SkillList()` to discover all available skills and their triggers.
Then call `Skill(name=<skill-name>)` to load a skill BEFORE acting on a non-trivial task.

**Rules:**
- Call `SkillList()` at the start of a session or when facing an unfamiliar task.
- Load skills BEFORE you act — loading after you've started is too late.
- Better to load too many skills than too few (~200 tokens each, cheap insurance).
- For project-specific skills, call `LoadProjectConfig(path=<project_root>)` first if not already done.
"""


def render_profile_skills(names: list[str]) -> str:
    """Preload the named skills' content into the prompt (an agent's declared skills are
    part of its equipment, not something to discover). Falls back to the generic
    SkillList() instruction when no name resolves."""
    from bouzecode.backend.tools.skill.loader import load_skills

    by_name = {s.name: s for s in load_skills()}
    blocks = []
    for name in names:
        skill = by_name.get(name)
        if skill is None:
            continue
        desc = (skill.description or "").strip()
        blocks.append(f"## {skill.name}\n{desc}\n\n{(skill.prompt or '').strip()}".strip())
    if not blocks:
        return get_skills_section()
    body = "\n\n---\n\n".join(blocks)
    return (
        "\n\n# Skills (préchargées pour cet agent)\n\n"
        "Ces skills font partie de ton équipement et sont déjà chargées ci-dessous — "
        "applique-les directement, inutile d'appeler SkillList()/Skill().\n\n" + body + "\n"
    )


def get_memory_context() -> str:
    """Load memory entries from ~/.bouzecode/memory/ and .bouzecode/memory/."""
    entries = []
    memory_dirs = [
        Path.home() / ".bouzecode" / "memory",
        Path.cwd() / ".bouzecode" / "memory",
    ]
    for mem_dir in memory_dirs:
        if not mem_dir.is_dir():
            continue
        for md_file in sorted(mem_dir.glob("*.md")):
            text = md_file.read_text(encoding="utf-8", errors="ignore")
            # Parse YAML frontmatter between --- lines
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = parts[1]
                    name = ""
                    description = ""
                    for line in frontmatter.splitlines():
                        if line.startswith("name:"):
                            name = line[5:].strip()
                        elif line.startswith("description:"):
                            description = line[12:].strip()
                    if name:
                        entries.append(f"- [{name}]({md_file.name}) — {description}")
    return "\n".join(entries)



def get_readme_navigation_section() -> str:
    """The code-navigation protocol, in the stable half of the prompt.

    It replaced the old `readme_sync/prompts/reader.md` block (293 permanent
    tokens), which walked a per-folder `## Subfolders` table that no longer
    exists — a protocol pointing at sections the repo does not have. That file
    has since been deleted, along with the conditional injection around it. This one is
    unconditional: the maps are generated on demand, so there is nothing to
    probe for, and it applies to every repository rather than to bouzecode only.
    """
    if not agents_map_enabled():
        return ""
    # Deliberately says nothing about HOW to read a symbol: that guidance is the
    # code profile's job (tests/backend/prompts/test_code_discovery_prompt.py
    # keeps it out of the agnostic noyau). This block only locates things.
    return (
        "\n\n# Codebase navigation\n\n"
        "`AgentsMap()` -> which folder. `SymbolMap(path=<folder>)` -> which symbol "
        "lives in it, and where.\n"
        "If you already know the file, skip `AgentsMap()` and go straight to its "
        "`SymbolMap`.\n"
    )


def agents_map_enabled() -> bool:
    """The single global escape hatch for the code-map feature."""
    from ..tools.agents_map import feature_enabled

    return feature_enabled()


def build_system_prompt_parts(config: dict | None = None) -> tuple[str, str]:
    """Return (stable, volatile) halves of the system prompt.

    Stable: identity, guidelines, platform hints, CLAUDE.md, memory, skills.
    Volatile: session context (date, cwd, git), plan mode block.

    The boundary is where an Anthropic-style cache_control breakpoint belongs.
    """
    import platform
    from ..agent.providers.registry import model_uses_native_tools
    model = config.get("model", "") if config else ""
    # The examples teach a PROTOCOL, so they follow the protocol switch — not the
    # provider. Keyed on the provider, an Anthropic model in native mode was still
    # taught XML it would never emit (~1 454 wasted characters every request).
    if model_uses_native_tools(model, config or {}):
        from ._embedded_data import TOOL_EXAMPLES_JSON as _examples
    else:
        from ._embedded_data import TOOL_EXAMPLES_XML as _examples
    template = SYSTEM_PROMPT_TEMPLATE
    if config and config.get("lean_turn_protocol"):
        from .lean_prompt import apply_lean_turn_protocol
        template = apply_lean_turn_protocol(template)
    stable = (
        template
        .replace("{platform_hints}", "")
        .replace("{claude_md}", "")
        .replace("{platform}", platform.system())
        .replace("{tool_examples}", _examples)
    )
    if config and config.get("thinking") and config.get("thinking_mode") == "loud":
        stable += THINK_OUT_LOUD_PROMPT
    memory_ctx = get_memory_context()
    if memory_ctx:
        stable += f"\n\n# Memory\nYour persistent memories:\n{memory_ctx}\n"
    # An agent's declared skills are part of its equipment: preload their bodies.
    # Otherwise emit the generic SkillList()/Skill() discovery instruction.
    profile_skills = config.get("_profile_skills") if config else None
    stable += render_profile_skills(profile_skills) if profile_skills else get_skills_section()
    stable += get_readme_navigation_section()

    # Active agent typology selected in-session via /agent <name>.
    agent_extra = config.get("_agent_system_prompt_extra", "") if config else ""
    if agent_extra:
        stable += f"\n\n# Active agent profile\n{agent_extra.strip()}\n"

    volatile = (
        "\n# Session Context\n"
        f"- Current date: {datetime.now().strftime('%Y-%m-%d %A')}\n"
        f"- Working directory: {Path.cwd()}\n"
    )
    git_info = get_git_info()
    if git_info:
        volatile += git_info

    # Contrat EXPLICITE pour un agent tournant dans un worktree ISOLÉ. Anciennement préfixé au
    # prompt user (dispatch._worktree_contract) — il pollue la lecture du ticket ; il vit
    # désormais ici, dans le system prompt. Armé par l'env BOUZECODE_WORKTREE_ROOT (posée au
    # spawn par le runner). Rend visible la règle du worktree et autorise l'action hors
    # worktree ordonnée par le ticket.
    #
    # 2026-07-28 : la formule « autorisé mais signalé » a été retirée. Le guard hors-worktree
    # qui produisait ce signal a été supprimé — sa trace out_of_worktree.jsonl n'avait AUCUN
    # lecteur, et le spawn_validator/mark_run_out_of_worktree_notified que la doc annonçait
    # n'a jamais existé. Promettre au modèle une surveillance inexistante lui apprend à
    # escompter le reste du prompt ; la vraie conséquence (non récolté) suffit et est vraie.
    worktree_root = os.environ.get("BOUZECODE_WORKTREE_ROOT", "") or ""
    if worktree_root:
        volatile += (
            f"\n\nTu travailles dans un worktree isolé : {worktree_root}. Tout ton travail se "
            "fait ICI ; tes diffs sont récoltés depuis CE worktree et mergés en fin de session "
            "— ce qui est écrit ailleurs n'est PAS récolté. Exception : suivre un chemin absolu "
            "externe UNIQUEMENT si le ticket l'ordonne explicitement (git -C, consigne "
            "cross-repo) ; c'est autorisé, mais ce que tu y écris ne sera pas récolté.\n"
        )
        # La branche EFFECTIVE, dite explicitement. Un ticket peut annoncer « ta branche de
        # travail = agent/X » alors que le provisioning a sorti agent/Y : l'agent livrait alors
        # au bon endroit techniquement, mais RAPPORTAIT le mauvais — un compte rendu trompeur
        # sans que personne mente. Nommer la branche réelle rend la contradiction visible AVANT
        # le rapport, pas après.
        branch = checked_out_branch(worktree_root)
        if branch:
            volatile += (
                f"Ta branche de travail est `{branch}` — c'est là que tes commits atterrissent. "
                "Si ton ticket en nomme une AUTRE, ne fais pas comme si de rien n'était : "
                "signale la contradiction dans ton rapport, elle signifie que ta livraison "
                "n'ira pas là où on l'attend.\n"
            )

    if config and config.get("permission_mode") == "plan":
        plan_file = config.get("_plan_file", "")
        volatile += PLAN_MODE_TEMPLATE.format(plan_file=plan_file)

    return stable, volatile


def build_system_prompt(config: dict | None = None) -> str:
    stable, volatile = build_system_prompt_parts(config)
    return stable + volatile


# Re-exported for backward compat: call sites (e.g. dispatch.py) import these
# from core.context. The implementations live in core.profile_extra.
from .profile_extra import (  # noqa: E402
    get_agent_profile_extra,
    get_default_agent_profile_extra,
)
