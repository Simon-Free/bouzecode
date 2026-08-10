# [desc] Implements /export, /copy, and /diff slash commands for conversation output and clipboard. [/desc]
"""Miscellaneous commands: /export, /copy, /diff."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

try:
    from bouzecode.ui.ansi import clr, ok, warn, err, info
except ImportError:
    import sys
    C = {"cyan": "\033[36m", "green": "\033[32m", "yellow": "\033[33m",
         "red": "\033[31m", "bold": "\033[1m", "dim": "\033[2m", "reset": "\033[0m"}
    def clr(text, *keys): return "".join(C[k] for k in keys) + str(text) + C["reset"]
    def info(msg):  print(clr(msg, "cyan"))
    def ok(msg):    print(clr(msg, "green"))
    def warn(msg):  print(clr(f"Warning: {msg}", "yellow"))
    def err(msg):   print(clr(f"Error: {msg}", "red"), file=sys.stderr)

try:
    from bouzecode.ui.tool_display import render_diff, _last_diffs
except ImportError:
    _last_diffs: dict[str, str] = {}
    _C = {"bold": "\033[1m", "green": "\033[32m", "red": "\033[31m",
          "cyan": "\033[36m", "reset": "\033[0m"}
    def render_diff(text: str):
        for line in text.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                print(_C["bold"] + line + _C["reset"])
            elif line.startswith("+"):
                print(_C["green"] + line + _C["reset"])
            elif line.startswith("-"):
                print(_C["red"] + line + _C["reset"])
            elif line.startswith("@@"):
                print(_C["cyan"] + line + _C["reset"])
            else:
                print(line)


def cmd_export(args: str, state, config) -> bool:
    """Export conversation history to a file.

    /export              -- export as markdown to .nano_claude/exports/
    /export <filename>   -- export to a specific file (.md or .json)
    """
    if not state.messages:
        err("No conversation to export.")
        return True

    arg = args.strip()
    if arg:
        out_path = Path(arg)
    else:
        export_dir = Path.cwd() / ".nano_claude" / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = export_dir / f"conversation_{ts}.md"

    is_json = out_path.suffix.lower() == ".json"

    if is_json:
        out_path.write_text(
            json.dumps(state.messages, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    else:
        lines = []
        for m in state.messages:
            role = m.get("role", "unknown")
            content = m.get("content", "")
            if isinstance(content, list):
                content = "(structured content)"
            if role == "user":
                lines.append(f"## User\n\n{content}\n")
            elif role == "assistant":
                lines.append(f"## Assistant\n\n{content}\n")
            elif role == "tool":
                name = m.get("name", "tool")
                lines.append(f"### Tool: {name}\n\n```\n{content[:2000]}\n```\n")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines), encoding="utf-8")

    info(f"Exported {len(state.messages)} messages to {out_path}")
    return True


def cmd_copy(args: str, state, config) -> bool:
    """Copy the last assistant response to clipboard.

    /copy   -- copy last assistant message to clipboard
    """
    last_reply = None
    for m in reversed(state.messages):
        if m.get("role") == "assistant":
            content = m.get("content", "")
            if isinstance(content, str) and content.strip():
                last_reply = content
                break

    if not last_reply:
        err("No assistant response to copy.")
        return True

    import subprocess as _sp
    import sys as _sys
    if _sys.platform == "win32":
        proc = _sp.Popen(["clip"], stdin=_sp.PIPE)
        proc.communicate(last_reply.encode("utf-16le"))
    elif _sys.platform == "darwin":
        proc = _sp.Popen(["pbcopy"], stdin=_sp.PIPE)
        proc.communicate(last_reply.encode("utf-8"))
    else:
        for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
            try:
                proc = _sp.Popen(cmd, stdin=_sp.PIPE)
                proc.communicate(last_reply.encode("utf-8"))
                break
            except FileNotFoundError:
                continue
        else:
            err("No clipboard tool found. Install xclip or xsel.")
            return True
    info(f"Copied {len(last_reply)} chars to clipboard.")
    return True


def cmd_diff(args: str, state, config) -> bool:
    """Show stored diffs from recent Edit/Write operations.

    /diff          -- list files with stored diffs
    /diff <path>   -- show colorized diff for that file
    """
    if not _last_diffs:
        info("No diffs stored. Diffs are captured from Edit/Write tool results.")
        return True
    if not args.strip():
        info("Stored diffs:")
        for fpath, diff_text in _last_diffs.items():
            added = sum(1 for l in diff_text.splitlines() if l.startswith("+") and not l.startswith("+++"))
            removed = sum(1 for l in diff_text.splitlines() if l.startswith("-") and not l.startswith("---"))
            print(clr(f"  {fpath}  (+{added}/-{removed})", "dim"))
        info("Use /diff <path> to view a specific diff.")
        return True
    target = args.strip()
    match = _last_diffs.get(target)
    if not match:
        for fpath, diff_text in _last_diffs.items():
            if fpath.endswith(target) or target.endswith(fpath):
                match = diff_text
                break
    if match:
        render_diff(match)
    else:
        err(f"No diff found for '{target}'. Use /diff to list available files.")
    return True


def cmd_compact(args: str, state, config) -> bool:
    """Manual compaction is disabled — context is pruned automatically each turn (minimal_payload)."""
    from bouzecode.ui.ansi import warn
    warn("Manual compaction is disabled. The wire payload is auto-pruned each turn; persistent state lives in the methodology note.")
    return True


def cmd_init(args: str, state, config) -> bool:
    """Initialize a CLAUDE.md file in the current directory.

    /init          -- create CLAUDE.md with a starter template
    """
    from pathlib import Path as _Path
    from bouzecode.ui.ansi import info, err

    target = _Path.cwd() / "CLAUDE.md"
    if target.exists():
        err(f"CLAUDE.md already exists at {target}")
        info("Edit it directly or delete it first.")
        return True

    project_name = _Path.cwd().name
    template = (
        f"# {project_name}\n\n"
        "## Project Overview\n"
        "<!-- Describe what this project does -->\n\n"
        "## Tech Stack\n"
        "<!-- Languages, frameworks, key dependencies -->\n\n"
        "## Conventions\n"
        "<!-- Coding style, naming conventions, patterns to follow -->\n\n"
        "## Important Files\n"
        "<!-- Key entry points, config files, etc. -->\n\n"
        "## Testing\n"
        "<!-- How to run tests, testing conventions -->\n\n"
    )
    target.write_text(template, encoding="utf-8")
    info(f"Created {target}")
    info("Edit it to give Claude context about your project.")
    return True

