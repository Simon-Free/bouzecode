# [desc] Builds the system prompt by assembling git info, CLAUDE.md, platform hints, skills, and memory context. [/desc]
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


def get_git_info() -> str:
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace").strip()
        status = subprocess.check_output(
            ["git", "status", "--short"],
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace").strip()
        log = subprocess.check_output(
            ["git", "log", "--oneline", "-5"],
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace").strip()
        parts = [f"- Git branch: {branch}"]
        if status:
            lines = status.split('\n')[:10]
            parts.append("- Git status:\n" + "\n".join(f"  {l}" for l in lines))
        if log:
            parts.append("- Recent commits:\n" + "\n".join(f"  {l}" for l in log.split('\n')))
        return "\n".join(parts) + "\n"
    except Exception:
        return ""





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



def build_system_prompt_parts(config: dict | None = None) -> tuple[str, str]:
    """Return (stable, volatile) halves of the system prompt.

    Stable: identity, guidelines, platform hints, CLAUDE.md, memory, skills.
    Volatile: session context (date, cwd, git), plan mode block.

    The boundary is where an Anthropic-style cache_control breakpoint belongs.
    """
    import platform
    from ..agent.providers.registry import detect_provider
    model = config.get("model", "") if config else ""
    provider = detect_provider(model) if model else "anthropic"
    if provider == "anthropic":
        from ._embedded_data import TOOL_EXAMPLES_XML as _examples
    else:
        from ._embedded_data import TOOL_EXAMPLES_JSON as _examples
    stable = (
        SYSTEM_PROMPT_TEMPLATE
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
    stable += get_skills_section()

    volatile = (
        "\n# Session Context\n"
        f"- Current date: {datetime.now().strftime('%Y-%m-%d %A')}\n"
        f"- Working directory: {Path.cwd()}\n"
    )
    git_info = get_git_info()
    if git_info:
        volatile += git_info

    if config and config.get("permission_mode") == "plan":
        plan_file = config.get("_plan_file", "")
        volatile += PLAN_MODE_TEMPLATE.format(plan_file=plan_file)

    return stable, volatile


def build_system_prompt(config: dict | None = None) -> str:
    stable, volatile = build_system_prompt_parts(config)
    return stable + volatile


_DEFAULT_PROFILE_EXTRA_CACHE: dict[str, str] = {}


def get_default_agent_profile_extra() -> str:
    """Return the `default` profile's system_prompt_extra (the code-agent layer).

    Resolved from .bouzecode/profiles in the cwd plus any registered extra dirs,
    cached per resolution root. Returns "" when no default profile is found.
    The dispatch layer appends this to the noyau for the top-level agent only.
    """
    return get_agent_profile_extra("default")


def get_agent_profile_extra(classification: str) -> str:
    """Return the system_prompt_extra for the given profile name.

    classification is either a task classification ('feature', 'bug', 'autre'/'default')
    or any explicit profile name (e.g. set via the --profile CLI flag).
    Resolved from .bouzecode/profiles in the cwd plus any registered extra dirs,
    cached per (classification, resolution root). Returns "" when profile is not found.
    """
    from .paths import get_extra_dirs
    from ..profiles import load_profiles_from_dir

    # 'autre'/empty map to 'default'; any other name resolves as-is
    profile_name = "default" if classification in ("", "autre", "default") else classification

    roots = [Path.cwd() / ".bouzecode", *get_extra_dirs()]
    cache_key = f"{profile_name}|" + "|".join(str(r) for r in roots)
    if cache_key in _DEFAULT_PROFILE_EXTRA_CACHE:
        return _DEFAULT_PROFILE_EXTRA_CACHE[cache_key]
    available: dict = {}
    for root in roots:
        available.update(load_profiles_from_dir(root / "profiles"))
    profile = available.get(profile_name)
    extra = (profile.system_prompt_extra or "").strip() if profile else ""
    _DEFAULT_PROFILE_EXTRA_CACHE[cache_key] = extra
    return extra
