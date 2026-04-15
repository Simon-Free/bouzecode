# [desc] Windows console input handler with paste-block collapsing, history, and special key support. [/desc]
"""Windows console input with paste block collapsing.

Uses ReadConsoleInputW (via paste_input.win_console) instead of msvcrt.getwch
so that arrow keys and the real character 'à' are unambiguously distinguished.
"""
from __future__ import annotations
import sys
import time

from paste_input.segments import (
    TextSegment, PastedBlock, Segment,
    render_line, reset_render_state, cursor_to_segment, total_display_len,
    result_text, merge_adjacent_text, split_and_insert_block,
    recalc_cursor_after_insert,
)
from paste_input import add_history, get_history, PASTE_BADGE_THRESHOLD
from paste_input.win_console import read_key, keydown_pending, drain_chars


def _sanitize(s: str) -> str:
    """Remove lone UTF-16 surrogates that crash stdout.write."""
    return s.encode("utf-8", "surrogatepass").decode("utf-8", "replace")


def _handle_backspace(segments, cursor_pos):
    if cursor_pos == 0:
        return segments, cursor_pos
    seg_i, offset = cursor_to_segment(segments, cursor_pos)
    seg = segments[seg_i]
    if isinstance(seg, PastedBlock):
        cursor_pos -= seg.display_len()
        segments.pop(seg_i)
        merge_adjacent_text(segments)
    elif isinstance(seg, TextSegment):
        if offset > 0:
            seg.text = seg.text[:offset - 1] + seg.text[offset:]
            cursor_pos -= 1
        elif seg_i > 0:
            prev = segments[seg_i - 1]
            if isinstance(prev, PastedBlock):
                cursor_pos -= prev.display_len()
                segments.pop(seg_i - 1)
                merge_adjacent_text(segments)
            elif isinstance(prev, TextSegment):
                cursor_pos -= 1
                prev.text = prev.text[:-1]
    if not segments:
        segments = [TextSegment()]
    return segments, cursor_pos


def _insert_paste(segments, cursor_pos, paste_text, as_block: bool):
    seg_i, offset = cursor_to_segment(segments, cursor_pos)
    seg = segments[seg_i]
    if as_block:
        if isinstance(seg, TextSegment):
            split_and_insert_block(segments, seg_i, offset, paste_text)
        else:
            block = PastedBlock(paste_text)
            segments.insert(seg_i + 1, block)
            segments.insert(seg_i + 2, TextSegment())
        cursor_pos = recalc_cursor_after_insert(segments, seg_i, offset, paste_text)
    else:
        if isinstance(seg, TextSegment):
            seg.text = seg.text[:offset] + paste_text + seg.text[offset:]
            cursor_pos += len(paste_text)
        else:
            segments.insert(seg_i + 1, TextSegment(paste_text))
            cursor_pos += len(paste_text)
    return segments, cursor_pos


def _handle_special_key(ch2, segments, cursor_pos, hist_idx):
    history = get_history()
    if ch2 == "K":  # Left
        if cursor_pos > 0:
            seg_i, offset = cursor_to_segment(segments, cursor_pos)
            seg = segments[seg_i]
            if isinstance(seg, PastedBlock) and offset > 0:
                cursor_pos -= seg.display_len()
            else:
                cursor_pos -= 1
            cursor_pos = max(0, cursor_pos)
    elif ch2 == "M":  # Right
        total = total_display_len(segments)
        if cursor_pos < total:
            seg_i, offset = cursor_to_segment(segments, cursor_pos)
            seg = segments[seg_i]
            if isinstance(seg, PastedBlock) and offset == 0:
                cursor_pos += seg.display_len()
            else:
                cursor_pos += 1
            cursor_pos = min(total, cursor_pos)
    elif ch2 == "H":  # Up
        if history and hist_idx > 0:
            hist_idx -= 1
            segments[:] = [TextSegment(history[hist_idx])]
            cursor_pos = total_display_len(segments)
    elif ch2 == "P":  # Down
        if hist_idx < len(history) - 1:
            hist_idx += 1
            segments[:] = [TextSegment(history[hist_idx])]
            cursor_pos = total_display_len(segments)
        elif hist_idx == len(history) - 1:
            hist_idx = len(history)
            segments[:] = [TextSegment()]
            cursor_pos = 0
    elif ch2 == "G":  # Home
        cursor_pos = 0
    elif ch2 == "O":  # End
        cursor_pos = total_display_len(segments)
    elif ch2 == "S":  # Delete
        total = total_display_len(segments)
        if cursor_pos < total:
            seg_i, offset = cursor_to_segment(segments, cursor_pos)
            seg = segments[seg_i]
            if isinstance(seg, PastedBlock):
                segments.pop(seg_i)
                merge_adjacent_text(segments)
            elif isinstance(seg, TextSegment) and offset < len(seg.text):
                seg.text = seg.text[:offset] + seg.text[offset + 1:]
        if not segments:
            segments[:] = [TextSegment()]
    return segments, cursor_pos, hist_idx


def read_input_windows(prompt: str) -> str:
    last_nl = prompt.rfind("\n")
    if last_nl != -1:
        sys.stdout.write(prompt[:last_nl + 1])
        sys.stdout.flush()
        prompt = prompt[last_nl + 1:]

    segments: list[Segment] = [TextSegment()]
    cursor_pos = 0
    hist_idx = len(get_history())
    reset_render_state()
    render_line(prompt, segments, cursor_pos)

    while True:
        ch, special = read_key()

        if special is not None:
            segments, cursor_pos, hist_idx = _handle_special_key(
                special, segments, cursor_pos, hist_idx
            )
            render_line(prompt, segments, cursor_pos)
            continue

        if ch in ("\r", "\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()
            result = result_text(segments)
            add_history(result)
            return result

        if ch == "\x03":
            sys.stdout.write("\n")
            sys.stdout.flush()
            raise KeyboardInterrupt

        if ch == "\x1a":
            raise EOFError

        if ch == "\x08":
            segments, cursor_pos = _handle_backspace(segments, cursor_pos)
            render_line(prompt, segments, cursor_pos)
            continue

        # ── Paste detection: rapid buffered chars ─────────────────────
        # Dead-key accents (e.g. ^ + e -> e-circumflex) put 1 extra char
        # in the buffer very quickly. Only treat as paste when >=3 chars.
        #
        # For large pastes (e.g. 150x150 chars), Windows delivers events
        # in chunks to the console buffer. We use bulk drain_chars() and
        # an adaptive gap timeout that grows with paste size so we never
        # break out early between chunks.
        if keydown_pending():
            paste_chars = [ch]
            # Bulk-drain everything currently buffered
            paste_chars.extend(drain_chars())
            # Adaptive gap: bigger paste -> longer wait for next chunk
            # Base 80ms, grows to 500ms for very large pastes
            gap = min(0.5, 0.08 + len(paste_chars) * 0.00002)
            t0 = time.monotonic()
            while (time.monotonic() - t0) < gap:
                if keydown_pending():
                    batch = drain_chars()
                    if batch:
                        paste_chars.extend(batch)
                        gap = min(0.5, 0.08 + len(paste_chars) * 0.00002)
                        t0 = time.monotonic()
                else:
                    time.sleep(0.005)
            if len(paste_chars) <= 2:
                # Dead-key or fast double-tap -- insert chars individually
                for c in paste_chars:
                    if c >= " ":
                        seg_i, offset = cursor_to_segment(segments, cursor_pos)
                        seg = segments[seg_i]
                        if isinstance(seg, TextSegment):
                            seg.text = seg.text[:offset] + c + seg.text[offset:]
                            cursor_pos += 1
                        elif isinstance(seg, PastedBlock):
                            segments.insert(seg_i + 1, TextSegment(c))
                            cursor_pos += 1
                render_line(prompt, segments, cursor_pos)
                continue
            paste_text = _sanitize("".join(paste_chars).replace("\r\n", "\n").replace("\r", "\n").rstrip("\n"))
            n_lines = paste_text.count("\n") + 1
            as_block = n_lines >= PASTE_BADGE_THRESHOLD
            segments, cursor_pos = _insert_paste(segments, cursor_pos, paste_text, as_block)
            render_line(prompt, segments, cursor_pos)
            continue

        # ── Normal character ──────────────────────────────────────────
        ch = _sanitize(ch)
        if ch >= " ":
            seg_i, offset = cursor_to_segment(segments, cursor_pos)
            seg = segments[seg_i]
            if isinstance(seg, TextSegment):
                seg.text = seg.text[:offset] + ch + seg.text[offset:]
                cursor_pos += 1
            elif isinstance(seg, PastedBlock):
                segments.insert(seg_i + 1, TextSegment(ch))
                cursor_pos += 1
            render_line(prompt, segments, cursor_pos)
