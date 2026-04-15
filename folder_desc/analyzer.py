# [desc] Analyzes code files in a folder, generates LLM-based descriptions, and prepends them as comments. [/desc]
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from folder_desc.desc_utils import (
    EXT_TO_STYLE,
    wrap_description,
    extract_description,
    _is_ignored,
)


def _call_llm_for_description(
    file_path: str, content: str, ext: str, config: dict | None = None,
) -> str | None:
    """Generate a one-line description via the bouzecode provider stack.

    Routes through `providers.stream` so the same retry/httpx/SSL handling
    used by the main chat applies here.
    """
    from providers import stream, AssistantTurn
    from config import load_config

    cfg = config if config is not None else load_config()
    model = cfg.get("model") or "claude-haiku-4-5-20251001"

    filename = Path(file_path).name
    snippet = content[:4000] + "\n[...]" if len(content) > 4000 else content
    user_msg = (
        f"File: {filename}\n\n```\n{snippet}\n```\n\n"
        "Generate a single-line description of what this file does. "
        "Reply ONLY with the plain text description (no comment syntax, no quotes). "
        "Keep it under 100 characters."
    )

    call_cfg = dict(cfg)
    call_cfg["max_tokens"] = 150
    call_cfg["thinking"] = False

    text = ""
    for event in stream(
        model=model,
        system="You write concise one-line file descriptions.",
        messages=[{"role": "user", "content": [{"type": "text", "text": user_msg}]}],
        tool_schemas=[],
        config=call_cfg,
    ):
        if isinstance(event, AssistantTurn):
            text = event.text
            break

    text = (text or "").strip()
    return text or None


def _collect_code_files(root: Path) -> list[Path]:
    files = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in EXT_TO_STYLE:
            continue
        if _is_ignored(p, root):
            continue
        files.append(p)
    return files


def _analyze_folder(params: dict, config: dict) -> str:
    folder = params["folder_path"]
    root = Path(folder)
    if not root.is_dir():
        return f"Error: {folder} is not a directory"

    files = _collect_code_files(root)
    if not files:
        return f"No code files found in {folder}"

    added = 0
    errors = []

    files_without_desc = [
        fp for fp in files
        if extract_description(fp.read_text(encoding="utf-8", errors="replace"))[0] is None
    ]
    skipped = len(files) - len(files_without_desc)

    if not files_without_desc:
        return f"All {len(files)} files in {folder} already have descriptions"

    def _process(fp: Path) -> tuple[str, str]:
        content = fp.read_text(encoding="utf-8", errors="replace")
        ext = fp.suffix.lower()

        new_desc = _call_llm_for_description(str(fp), content, ext, config)
        if not new_desc:
            return "error", f"LLM returned empty for {fp.name}"

        wrapped = wrap_description(new_desc, ext)
        if not wrapped:
            return "skip", f"No comment style for {ext}"

        lines = content.splitlines(keepends=True)
        if lines and lines[0].startswith("#!"):
            new_lines = [lines[0], wrapped + "\n"] + lines[1:]
        else:
            new_lines = [wrapped + "\n"] + lines

        fp.write_text("".join(new_lines), encoding="utf-8", newline="")
        return "added", f"added: {fp.relative_to(root)}"

    from tqdm import tqdm

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_process, fp): fp for fp in files_without_desc}
        progress = tqdm(
            as_completed(futures),
            total=len(files_without_desc),
            desc=f"Analyse automatique ({root.name})",
            unit="file",
            ncols=80,
            file=sys.stderr,
            leave=False,
        )
        for fut in progress:
            status, msg = fut.result()
            if status == "added":
                added += 1
            elif status == "error":
                errors.append(msg)

    parts = [f"Analyzed {len(files_without_desc)}/{len(files)} files in {folder}"]
    parts.append(f"  Added: {added}, Skipped (already had desc): {skipped}, Errors: {len(errors)}")
    if errors:
        parts.append("Errors:\n  " + "\n  ".join(errors[:10]))
    return "\n".join(parts)


def _count_files_with_description(files: list[Path]) -> int:
    with_desc = 0
    for p in files:
        content = p.read_text(encoding="utf-8", errors="replace")
        desc, _, _ = extract_description(content)
        if desc:
            with_desc += 1
    return with_desc
