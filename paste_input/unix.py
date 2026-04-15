# [desc] Unix tty-based line input with paste detection, segment editing, history, and cursor navigation. [/desc]
"""Unix tty-based input with paste block collapsing."""
from __future__ import annotations
import sys

from paste_input.segments import (
    TextSegment, PastedBlock, Segment,
    render_line, reset_render_state, cursor_to_segment, total_display_len,
    result_text, merge_adjacent_text, split_and_insert_block,
    recalc_cursor_after_insert,
)
from paste_input import add_history, get_history, PASTE_BADGE_THRESHOLD


def _read_escape_seq(fd) -> str:
    import select
    buf = ""
    while True:
        ready = select.select([fd], [], [], 0.05)[0]
        if not ready:
            break
        c = sys.stdin.read(1)
        buf += c
        if c.isalpha() or c == "~":
            break
    return buf


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


def _insert_paste(segments, cursor_pos, paste_text):
    n_lines = paste_text.count("\n") + 1
    as_block = n_lines >= PASTE_BADGE_THRESHOLD
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


def _handle_arrow(seq, segments, cursor_pos, hist_idx):
    history = get_history()
    if seq == "[A":  # Up
        if history and hist_idx > 0:
            hist_idx -= 1
            segments[:] = [TextSegment(history[hist_idx])]
            cursor_pos = total_display_len(segments)
    elif seq == "[B":  # Down
        if hist_idx < len(history) - 1:
            hist_idx += 1
            segments[:] = [TextSegment(history[hist_idx])]
            cursor_pos = total_display_len(segments)
        elif hist_idx == len(history) - 1:
            hist_idx = len(history)
            segments[:] = [TextSegment()]
            cursor_pos = 0
    elif seq == "[C":  # Right
        total = total_display_len(segments)
        if cursor_pos < total:
            seg_i, offset = cursor_to_segment(segments, cursor_pos)
            seg = segments[seg_i]
            if isinstance(seg, PastedBlock) and offset == 0:
                cursor_pos += seg.display_len()
            else:
                cursor_pos += 1
            cursor_pos = min(total, cursor_pos)
    elif seq == "[D":  # Left
        if cursor_pos > 0:
            seg_i, offset = cursor_to_segment(segments, cursor_pos)
            seg = segments[seg_i]
            if isinstance(seg, PastedBlock) and offset > 0:
                cursor_pos -= seg.display_len()
            else:
                cursor_pos -= 1
            cursor_pos = max(0, cursor_pos)
    elif seq == "[H":  # Home
        cursor_pos = 0
    elif seq == "[F":  # End
        cursor_pos = total_display_len(segments)
    elif seq == "[3~":  # Delete
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


def read_input_unix(prompt: str) -> str:
    import tty
    import termios

    last_nl = prompt.rfind("\n")
    if last_nl != -1:
        sys.stdout.write(prompt[:last_nl + 1])
        sys.stdout.flush()
        prompt = prompt[last_nl + 1:]

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    segments: list[Segment] = [TextSegment()]
    cursor_pos = 0
    hist_idx = len(get_history())

    sys.stdout.write("\x1b[?2004h")  # enable bracketed paste
    sys.stdout.flush()

    try:
        tty.setraw(fd)
        reset_render_state()
        render_line(prompt, segments, cursor_pos)

        while True:
            ch = sys.stdin.read(1)

            # ── Escape sequences ──────────────────────────────────────
            if ch == "\x1b":
                seq = _read_escape_seq(fd)
                if seq == "[200~":
                    paste_buf = []
                    while True:
                        c = sys.stdin.read(1)
                        if c == "\x1b":
                            end_seq = _read_escape_seq(fd)
                            if end_seq == "[201~":
                                break
                            paste_buf.append("\x1b" + end_seq)
                        else:
                            paste_buf.append(c)
                    paste_text = "".join(paste_buf).rstrip("\n")
                    segments, cursor_pos = _insert_paste(segments, cursor_pos, paste_text)
                    render_line(prompt, segments, cursor_pos)
                    continue
                segments, cursor_pos, hist_idx = _handle_arrow(
                    seq, segments, cursor_pos, hist_idx
                )
                render_line(prompt, segments, cursor_pos)
                continue

            if ch in ("\r", "\n"):
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                result = result_text(segments)
                add_history(result)
                return result

            if ch == "\x03":
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                raise KeyboardInterrupt

            if ch == "\x04":
                if total_display_len(segments) == 0:
                    raise EOFError
                continue

            if ch in ("\x7f", "\x08"):
                segments, cursor_pos = _handle_backspace(segments, cursor_pos)
                render_line(prompt, segments, cursor_pos)
                continue

            if ch == "\x15":  # Ctrl+U clear line
                segments = [TextSegment()]
                cursor_pos = 0
                render_line(prompt, segments, cursor_pos)
                continue

            if ch == "\x01":  # Ctrl+A home
                cursor_pos = 0
                render_line(prompt, segments, cursor_pos)
                continue

            if ch == "\x05":  # Ctrl+E end
                cursor_pos = total_display_len(segments)
                render_line(prompt, segments, cursor_pos)
                continue

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

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write("\x1b[?2004l")
        sys.stdout.flush()
