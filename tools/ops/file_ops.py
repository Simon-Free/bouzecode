# [desc] File operations (read, write, edit) with unified diff generation and line-ending normalization. [/desc]
"""File operations: read, write, edit, diff helpers."""
import difflib
import time
from pathlib import Path

from tools.state import _track_read, _stale_edit_warning, _update_mtime_after_write, record_file_snapshot


def _write_text_with_retry(path: Path, content: str, attempts: int = 5, base_delay: float = 0.05) -> None:
    # Windows: indexers/watchers (PyCharm, AV, Flask reloader) hold transient share-read
    # locks. Exclusive write then fails with PermissionError. Retry with backoff.
    for i in range(attempts):
        try:
            path.write_text(content, encoding="utf-8", newline="")
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(base_delay * (2 ** i))


def generate_unified_diff(old, new, filename, context_lines=3):
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines,
        fromfile=f"a/{filename}", tofile=f"b/{filename}", n=context_lines)
    return "".join(diff)


def maybe_truncate_diff(diff_text, max_lines=80):
    lines = diff_text.splitlines()
    if len(lines) <= max_lines:
        return diff_text
    shown = lines[:max_lines]
    remaining = len(lines) - max_lines
    return "\n".join(shown) + f"\n\n[... {remaining} more lines ...]"


def _read(file_path: str, limit: int = None, offset: int = None) -> str:
    p = Path(file_path)
    if not p.exists():
        return f"Error: file not found: {file_path}"
    if p.is_dir():
        return f"Error: {file_path} is a directory"
    try:
        lines = p.read_text(encoding="utf-8", errors="replace", newline="").splitlines(keepends=True)
        start = offset or 0
        chunk = lines[start:start + limit] if limit else lines[start:]
        if not chunk:
            return "(empty file)"
        _track_read(file_path, content="".join(lines))
        return "".join(f"{start + i + 1:6}\t{l}" for i, l in enumerate(chunk))
    except Exception as e:
        return f"Error: {e}"


def _write(file_path: str, content: str) -> str:
    p = Path(file_path)
    try:
        is_new = not p.exists()
        old_content = "" if is_new else p.read_text(encoding="utf-8", errors="replace", newline="")
        p.parent.mkdir(parents=True, exist_ok=True)
        _write_text_with_retry(p, content)
        _update_mtime_after_write(file_path, content=content)
        record_file_snapshot(file_path, old_content, content, is_new=is_new)
        if is_new:
            lc = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            return f"Created {file_path} ({lc} lines)"
        filename = p.name
        diff = generate_unified_diff(old_content, content, filename)
        if not diff:
            return f"No changes in {file_path}"
        truncated = maybe_truncate_diff(diff)
        return f"File updated \u2014 {file_path}:\n\n{truncated}"
    except Exception as e:
        return f"Error: {e}"


def _edit(file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    p = Path(file_path)
    if not p.exists():
        return f"Error: file not found: {file_path}"
    stale_warning = _stale_edit_warning(file_path)
    try:
        content = p.read_text(encoding="utf-8", errors="replace", newline="")

        crlf_count = content.count("\r\n")
        lf_count = content.count("\n")
        is_pure_crlf = crlf_count > 0 and crlf_count == lf_count

        content_norm = content.replace("\r\n", "\n")
        old_norm = old_string.replace("\r\n", "\n")
        new_norm = new_string.replace("\r\n", "\n")

        count = content_norm.count(old_norm)
        if count == 0:
            return "Error: old_string not found in file. Please ensure EXACT match, including all exact leading spaces/indentation and trailing newlines."
        if count > 1 and not replace_all:
            return (f"Error: old_string appears {count} times. "
                    "Provide more context to make it unique, or use replace_all=true.")

        old_content_norm = content_norm
        new_content_norm = content_norm.replace(old_norm, new_norm) if replace_all else \
                           content_norm.replace(old_norm, new_norm, 1)

        if is_pure_crlf:
            final_content = new_content_norm.replace("\n", "\r\n")
            old_content_final = content
        else:
            final_content = new_content_norm
            old_content_final = content_norm

        _write_text_with_retry(p, final_content)
        _update_mtime_after_write(file_path, content=final_content)
        record_file_snapshot(file_path, content, final_content)
        filename = p.name
        diff = generate_unified_diff(old_content_final, final_content, filename)
        result = f"Changes applied to {filename}:\n\n{diff}"
        if stale_warning:
            result = stale_warning + "\n" + result
        return result
    except Exception as e:
        return f"Error: {e}"
