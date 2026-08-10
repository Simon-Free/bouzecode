# [desc] File operations (read, write, edit) with unified diff generation and line-ending normalization. [/desc]
"""File operations: read, write, edit, diff helpers."""
import difflib
import time
from pathlib import Path

from ...tools.state import _track_read, _stale_edit_warning, _update_mtime_after_write, record_file_snapshot, read_text_raw
from .edit_context import build_edit_context, find_enclosing_symbol
from .edit_match import describe_missing_old_string, find_uniform_reindent, reindent_block


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


def _read(file_path: str, limit: int = None, offset: int = None, symbol: str = None) -> str:
    from .scratch import lookup_temp
    _temp_real = lookup_temp(file_path)
    p = Path(_temp_real) if _temp_real is not None else Path(file_path)
    if not p.exists():
        from .read_fallback import path_not_found_message, resolve_missing_path
        resolved, candidates = resolve_missing_path(file_path)
        if resolved is None:
            return path_not_found_message(file_path, candidates)
        file_path, p = resolved, Path(resolved)
    if p.is_dir():
        return f"Error: {file_path} is a directory"
    _IMAGE_MIME = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    media_type = _IMAGE_MIME.get(p.suffix.lower())
    if media_type is not None:
        import base64
        try:
            b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        except Exception as e:
            return f"Error: {e}"
        return f"__BOUZE_IMAGE__:{media_type}:{b64}"
    try:
        content = read_text_raw(p)
        lines = content.splitlines(keepends=True)
        if symbol:
            from ..folder_desc.symbols import find_symbol
            rng = find_symbol(file_path, symbol, content)
            if rng is None:
                from .read_fallback import whole_file_for_unknown_symbol
                _track_read(file_path, content=content)
                return whole_file_for_unknown_symbol(file_path, symbol, content)
            s, e = rng[0] - 1, rng[1]
            _track_read(file_path, content=content)
            return "".join(f"{s + i + 1:6}\t{l}" for i, l in enumerate(lines[s:e]))
        start = offset or 0
        chunk = lines[start:start + limit] if limit else lines[start:]
        if not chunk:
            return "(empty file)"
        _track_read(file_path, content=content)
        return "".join(f"{start + i + 1:6}\t{l}" for i, l in enumerate(chunk))
    except Exception as e:
        return f"Error: {e}"


def _write(file_path: str, content: str, temp: bool = False) -> str:
    if temp:
        from .scratch import resolve_scratch_path, register_temp
        real = resolve_scratch_path(file_path)
        register_temp(file_path, real)
        real.parent.mkdir(parents=True, exist_ok=True)
        _write_text_with_retry(real, content)
        lc = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        return (
            f"[scratch] Created temp file {file_path} ({lc} lines) \u2014 not tracked by git, destroyed at session end.\n"
            f"\u2192 r\u00e9el: {real}\n"
            f"Bash/Glob/Grep ne voient pas le chemin logique \u00ab {file_path} \u00bb ; utilise le chemin r\u00e9el ci-dessus dans les commandes shell "
            f"(Bash substitue automatiquement le chemin logique par le r\u00e9el, donc `python {file_path}` fonctionne aussi)."
        )
    p = Path(file_path)
    try:
        is_new = not p.exists()
        old_content = "" if is_new else read_text_raw(p)
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


def _edit(file_path: str, old_string: str, new_string: str, replace_all: bool = False, temp: bool = False) -> str:
    if temp:
        from .scratch import lookup_temp
        real = lookup_temp(file_path)
        if real is None:
            return f"Error: no temp file registered for {file_path}. Write it first with temp=True."
        p = Path(real)
    else:
        p = Path(file_path)
    if not p.exists():
        return f"Error: file not found: {file_path}"
    stale_warning = _stale_edit_warning(file_path)
    try:
        content = read_text_raw(p)

        crlf_count = content.count("\r\n")
        lf_count = content.count("\n")
        is_pure_crlf = crlf_count > 0 and crlf_count == lf_count

        content_norm = content.replace("\r\n", "\n")
        old_norm = old_string.replace("\r\n", "\n")
        new_norm = new_string.replace("\r\n", "\n")

        reindent_note = ""
        count = content_norm.count(old_norm)
        if count == 0:
            # The ONE tolerated repair: the block is present but uniformly shifted.
            # Everything else (one line differing in content, several lines
            # differing) is refused — applying the edit on the file's own line
            # would silently delete text the model never saw.
            repaired = find_uniform_reindent(content_norm, old_norm)
            shifted_new = reindent_block(new_norm, repaired[1]) if repaired else None
            if shifted_new is None:
                return describe_missing_old_string(content_norm, old_norm, file_path)
            old_norm, delta = repaired[0], repaired[1]
            new_norm = shifted_new
            count = 1
            reindent_note = (
                f"NOTE: old_string was re-indented automatically ({delta:+d} columns, "
                f"uniform on every line, unique match in the file). new_string was "
                f"shifted by the same delta.\n"
            )
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
        diff = maybe_truncate_diff(diff, max_lines=40)
        result = f"Changes applied to {filename}:\n\n{diff}"

        # Enriched context: show region around edit with line numbers + enclosing symbol
        # Skip context when diff is already large (truncated) — the diff IS the context
        diff_line_count = diff.count("\n") + 1
        ctx = build_edit_context(final_content, new_norm) if diff_line_count <= 30 else ""
        if ctx:
            # Find the line of new_string for symbol resolution
            new_idx = final_content.find(new_norm)
            mid_line = final_content[:new_idx].count("\n") + 1 if new_idx >= 0 else 1
            symbol = find_enclosing_symbol(file_path, mid_line, final_content)
            symbol_info = f" ({symbol} L{mid_line})" if symbol else f" (L{mid_line})"
            result += f"\n\nContext{symbol_info}:\n{ctx}"

        if reindent_note:
            result = reindent_note + result
        if stale_warning:
            result = stale_warning + "\n" + result
        return result
    except Exception as e:
        return f"Error: {e}"
