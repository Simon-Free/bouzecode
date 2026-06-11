# [desc] File operations (read, write, edit) with unified diff generation and line-ending normalization. [/desc]
"""File operations: read, write, edit, diff helpers."""
import difflib
import time
from pathlib import Path

from ...tools.state import _track_read, _stale_edit_warning, _update_mtime_after_write, record_file_snapshot


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
    p = Path(file_path)
    if not p.exists():
        return f"Error: file not found: {file_path}"
    if p.is_dir():
        return f"Error: {file_path} is a directory"
    try:
        content = p.read_text(encoding="utf-8", errors="replace", newline="")
        lines = content.splitlines(keepends=True)
        if symbol:
            from ..folder_desc.symbols import find_symbol, extract_symbols
            rng = find_symbol(file_path, symbol, content)
            if rng is None:
                syms = extract_symbols(file_path, content)
                names = []
                for s in syms:
                    names.append(s.name)
                    for c in s.children:
                        names.append(f"{s.name}.{c.name}")
                avail = ", ".join(names[:30]) if names else "(no symbols detected)"
                return f"Error: symbol '{symbol}' not found in {file_path}. Available symbols: {avail}"
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


def _find_enclosing_symbol(file_path: str, line_no: int, content: str) -> str | None:
    """Return 'Class.method' or 'function' name enclosing line_no (1-based)."""
    try:
        from ..folder_desc.symbols import extract_symbols
        symbols = extract_symbols(file_path, content)
        for sym in symbols:
            if sym.start_line <= line_no <= sym.end_line:
                for child in sym.children:
                    if child.start_line <= line_no <= child.end_line:
                        return f"{sym.name}.{child.name}"
                return sym.name
    except Exception:
        pass
    return None


def _build_edit_context(content: str, new_string: str, file_path: str, context_lines: int = 10) -> str:
    """Build numbered context around new_string in content. Truncate middle if huge."""
    lines = content.split("\n")
    new_norm = new_string.replace("\r\n", "\n")
    # Find where new_string starts in content
    idx = content.find(new_norm)
    if idx == -1:
        return ""
    start_line = content[:idx].count("\n")  # 0-based line of first char
    new_lines_count = new_norm.count("\n") + 1
    end_line = start_line + new_lines_count - 1  # 0-based inclusive

    ctx_start = max(0, start_line - context_lines)
    ctx_end = min(len(lines) - 1, end_line + context_lines)

    region = lines[ctx_start:ctx_end + 1]

    # Truncate middle if region is too large (>40 lines)
    max_region = 40
    if len(region) > max_region:
        keep_top = max_region // 2
        keep_bot = max_region - keep_top
        omitted = len(region) - keep_top - keep_bot
        region = region[:keep_top] + [f"    ... ({omitted} lines omitted) ..."] + region[-keep_bot:]
        # Adjust numbering for bottom part
        numbered = []
        for i, line in enumerate(region[:keep_top]):
            numbered.append(f"{ctx_start + i + 1:6}\t{line}")
        numbered.append(f"{'':6}\t{region[keep_top]}")
        for i, line in enumerate(region[keep_top + 1:]):
            numbered.append(f"{ctx_end + 1 - keep_bot + i:6}\t{line}")
        return "\n".join(numbered)

    return "\n".join(f"{ctx_start + i + 1:6}\t{line}" for i, line in enumerate(region))


def _fuzzy_find_old_string(content: str, old_string: str, context_lines: int = 7) -> str:
    """Find the closest match to old_string in content and return context around it."""
    from difflib import SequenceMatcher
    old_norm = old_string.replace("\r\n", "\n")
    lines = content.split("\n")
    old_lines = old_norm.split("\n")

    if not old_lines or not lines:
        return ""

    best_ratio = 0.0
    best_start = 0
    window = len(old_lines)

    # Slide a window of old_lines size across content lines
    for i in range(max(1, len(lines) - window + 1)):
        candidate = "\n".join(lines[i:i + window])
        ratio = SequenceMatcher(None, old_norm, candidate).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = i

    if best_ratio < 0.4:
        return ""

    ctx_start = max(0, best_start - context_lines)
    ctx_end = min(len(lines) - 1, best_start + window - 1 + context_lines)
    region = lines[ctx_start:ctx_end + 1]
    header = f"Closest match (similarity {best_ratio:.0%}) at lines {best_start + 1}-{best_start + window}:"
    numbered = "\n".join(f"{ctx_start + i + 1:6}\t{line}" for i, line in enumerate(region))
    return f"{header}\n{numbered}"


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
            fuzzy = _fuzzy_find_old_string(content_norm, old_string)
            msg = "Error: old_string not found in file. Please ensure EXACT match, including all exact leading spaces/indentation and trailing newlines."
            if fuzzy:
                msg += f"\n\n{fuzzy}"
            return msg
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
        ctx = _build_edit_context(final_content, new_string, file_path) if diff_line_count <= 30 else ""
        if ctx:
            # Find the line of new_string for symbol resolution
            new_idx = final_content.find(new_norm)
            mid_line = final_content[:new_idx].count("\n") + 1 if new_idx >= 0 else 1
            symbol = _find_enclosing_symbol(file_path, mid_line, final_content)
            symbol_info = f" ({symbol} L{mid_line})" if symbol else f" (L{mid_line})"
            result += f"\n\nContext{symbol_info}:\n{ctx}"

        if stale_warning:
            result = stale_warning + "\n" + result
        return result
    except Exception as e:
        return f"Error: {e}"
