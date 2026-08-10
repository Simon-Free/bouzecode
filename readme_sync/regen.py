# [desc] Regenerates a folder's AGENTS.md via an LLM call, using the human README.md as read-only context. [/desc]
from __future__ import annotations

import os
from pathlib import Path

from .hashing import (
    DOC_NAME,
    code_files,
    compute_manifest,
    read_lock,
    write_lock,
    _manifest_diff,
)
from .propagate import propagate_up


DEFAULT_MODEL = "claude-sonnet-4-5"
_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def api_key() -> str | None:
    """The Anthropic key from the environment, or None if unset."""
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")


def model_name() -> str:
    return os.environ.get("READMESYNC_MODEL", DEFAULT_MODEL)


def system_prompt() -> str:
    """The regen contract, used as the LLM system prompt."""
    return (_PROMPTS_DIR / "regen_system.md").read_text(encoding="utf-8")


def _rel(folder: Path, root: Path) -> str:
    try:
        rel = str(folder.relative_to(root))
        return rel if rel and rel != "." else root.name
    except ValueError:
        return str(folder)


def changed_vs_unchanged(folder: Path) -> tuple[list[Path], list[str]]:
    """Split a folder's code files into (changed paths, unchanged names).

    No lock or a diverging entry => the file is 'changed' (its full content is
    sent to the LLM). Everything else is 'unchanged' (name only).
    """
    files = code_files(folder)
    lock = read_lock(folder)
    if lock is None:
        return files, []
    reasons = _manifest_diff(folder, lock)
    changed_names = set()
    for reason in reasons:
        if reason.startswith("new file: "):
            changed_names.add(reason[len("new file: "):])
        elif reason.startswith("hash changed: "):
            changed_names.add(reason[len("hash changed: "):])
    changed = [p for p in files if p.name in changed_names]
    unchanged = [p.name for p in files if p.name not in changed_names]
    return changed, unchanged


def build_user_message(folder: Path, root: Path) -> str:
    """Assemble the single user message for regenerating AGENTS.md.

    Includes the current AGENTS.md (if any), the folder's human README.md as
    READ-ONLY context (never rewritten), the full body of changed/new code
    files, and the names of unchanged files.
    """
    changed, unchanged = changed_vs_unchanged(folder)
    doc = folder / DOC_NAME
    current = doc.read_text(encoding="utf-8") if doc.exists() else "(none)"

    parts = [f"# Folder to document: {_rel(folder, root)}", ""]
    parts.append("## Current AGENTS.md")
    parts.append(current)
    parts.append("")

    human_readme = folder / "README.md"
    if human_readme.exists():
        parts.append("## Human README.md (read-only context — DO NOT reproduce or rewrite it)")
        parts.append(human_readme.read_text(encoding="utf-8"))
        parts.append("")

    parts.append("## Changed / new code files (full content)")
    if changed:
        for p in changed:
            parts.append(f"### {p.name}")
            parts.append("```python")
            parts.append(p.read_text(encoding="utf-8"))
            parts.append("```")
    else:
        parts.append("(none — all files unchanged)")
    parts.append("")
    parts.append("## Unchanged code files (names only)")
    parts.append(", ".join(unchanged) if unchanged else "(none)")
    parts.append("")
    parts.append("Regenerate AGENTS.md for this folder following the contract. "
                 "Output ONLY the markdown, no code fences around the whole thing.")
    return "\n".join(parts)


def _strip_outer_fence(text: str) -> str:
    """Drop a ```markdown ... ``` wrapper if the model added one."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip() + "\n"
    return stripped + "\n"


def _make_client():
    import anthropic
    import httpx

    # Root-agnostic client (only httpx + anthropic, no bouzecode import): the
    # generous read timeout matters because a regen turn streams a whole README.
    timeout = httpx.Timeout(connect=10, read=60, write=30, pool=10)
    http_client = httpx.Client(timeout=timeout)
    return anthropic.Anthropic(
        base_url=os.environ.get("ANTHROPIC_BASE_URL") or None,
        api_key=api_key(),
        http_client=http_client,
        max_retries=3,
    )


def regen_folder(folder: Path, root: Path, model: str | None = None, client=None) -> Path:
    """One LLM call: regenerate folder/AGENTS.md and rewrite its lock fresh.

    Always generates via the LLM and writes AGENTS.md — never touches the
    folder's human README.md (passed to the model as read-only context only).
    """
    folder = folder.resolve()
    root = root.resolve()
    if client is None:
        client = _make_client()
    resp = client.messages.create(
        model=model or model_name(),
        max_tokens=4096,
        system=system_prompt(),
        messages=[{"role": "user", "content": build_user_message(folder, root)}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text")
    (folder / DOC_NAME).write_text(_strip_outer_fence(text), encoding="utf-8")
    write_lock(folder, stale=False)
    propagate_up(folder, root)
    return folder
