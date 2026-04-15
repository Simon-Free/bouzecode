# [desc] Builds the system prompt by assembling git info, CLAUDE.md, platform hints, skills, and memory context. [/desc]
import os
import subprocess
from pathlib import Path
from datetime import datetime

from memory import get_memory_context

_TEMPLATE_PATH = Path(__file__).parent / "system_prompt_template.txt"
SYSTEM_PROMPT_TEMPLATE = _TEMPLATE_PATH.read_text(encoding="utf-8")


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


def get_claude_md() -> str:
    content_parts = []

    global_md = Path.home() / ".claude" / "CLAUDE.md"
    if global_md.exists():
        try:
            content_parts.append(f"[Global CLAUDE.md]\n{global_md.read_text()}")
        except Exception:
            pass

    p = Path.cwd()
    for _ in range(10):
        candidate = p / "CLAUDE.md"
        if candidate.exists():
            try:
                content_parts.append(f"[Project CLAUDE.md: {candidate}]\n{candidate.read_text()}")
            except Exception:
                pass
            break
        parent = p.parent
        if parent == p:
            break
        p = parent

    if not content_parts:
        return ""
    return "\n# Memory / CLAUDE.md\n" + "\n\n".join(content_parts) + "\n"


def get_platform_hints() -> str:
    import platform as _plat
    if _plat.system() == "Windows":
        return (
            "\n## Windows Shell Hints\n"
            "You are on Windows. Do NOT use Unix commands. Use these instead:\n"
            "- `type file.txt` instead of `cat file.txt`\n"
            "- `type file.txt | findstr /n /i \"pattern\"` instead of `grep`\n"
            "- `powershell -Command \"Get-Content file.txt -Tail 20\"` instead of `tail -n 20`\n"
            "- `powershell -Command \"Get-Content file.txt -Head 20\"` instead of `head -n 20`\n"
            "- `dir /s /b *.py` or `powershell -Command \"Get-ChildItem -Recurse -Filter *.py\"` instead of `find . -name '*.py'`\n"
            "- `del file.txt` instead of `rm file.txt`\n"
            "- `mkdir folder` works on both (no -p needed)\n"
            "- `copy` / `move` instead of `cp` / `mv`\n"
            "- Use `&&` to chain commands, not `;`\n"
            "- Paths use backslashes `\\` but forward slashes `/` also work in most cases\n"
            "- Python is available: `python -c \"...\"` works for complex text processing\n"
        )
    return ""


def get_skills_section() -> str:
    from skill.loader import load_skills
    skills = load_skills()
    if not skills:
        return ""
    lines = [
        "",
        "# Available Skills",
        "Invoke any of these via the `Skill` tool with `name=<skill-name>`. "
        "Each skill expands to a detailed prompt that guides you. "
        "BEFORE starting a non-trivial task, check this list for a matching skill and use it.",
        "",
    ]
    for skill in sorted(skills, key=lambda s: s.name):
        description = (skill.description or "").replace("\n", " ").strip()
        if len(description) > 160:
            description = description[:157] + "..."
        lines.append(f"- **{skill.name}** — {description}")
    return "\n".join(lines) + "\n"


def build_system_prompt(config: dict | None = None) -> str:
    import platform
    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        date=datetime.now().strftime("%Y-%m-%d %A"),
        cwd=str(Path.cwd()),
        platform=platform.system(),
        platform_hints=get_platform_hints(),
        git_info=get_git_info(),
        claude_md=get_claude_md(),
    )
    memory_ctx = get_memory_context()
    if memory_ctx:
        prompt += f"\n\n# Memory\nYour persistent memories:\n{memory_ctx}\n"
    prompt += get_skills_section()

    if config and config.get("permission_mode") == "plan":
        plan_file = config.get("_plan_file", "")
        prompt += (
            "\n\n# Plan Mode (ACTIVE)\n"
            "You are in PLAN MODE. Important rules:\n"
            "- You may ONLY read/analyze code using Read, Glob, Grep, WebFetch, WebSearch\n"
            f"- You may ONLY write to the plan file: {plan_file}\n"
            "- Do NOT attempt to Write/Edit any other files — those operations will be blocked\n"
            "- You CAN describe Python scripts to execute — include them as code blocks in the plan\n"
            "- Use TaskCreate to break down your plan into trackable steps if appropriate\n"
            "- Write a detailed, actionable implementation plan to the plan file\n"
            "- When the plan is ready, tell the user to run /plan done to begin implementation\n"
            "\n## Plan Structure\n"
            "Your plan should include these sections when relevant:\n"
            "- **Python scripts to execute**: Python scripts with ```python code blocks\n"
        )

    return prompt
