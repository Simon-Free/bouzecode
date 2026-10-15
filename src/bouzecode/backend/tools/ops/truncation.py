# [desc] Helper to truncate large tool outputs and save full content to a readable file for later access. [/desc]
from __future__ import annotations
from bouzecode.paths import data_dir as bouzecode_data_dir

import os
import time
from pathlib import Path


def _get_output_dir() -> Path:
    """Return directory for saved tool outputs."""
    custom = os.environ.get("BOUZECODE_TOOL_OUTPUT_DIR")
    if custom:
        d = Path(custom)
    else:
        d = bouzecode_data_dir() / "tool_outputs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def truncate_tool_output(
    output: str,
    tool_name: str,
    max_lines: int = 200,
    max_chars: int = 8000,
    head_lines: int = 80,
    tail_lines: int = 160,
) -> str:
    """Truncate output if it exceeds thresholds, saving full output to a file.

    Returns the original output if under thresholds, otherwise the HEAD plus the
    TAIL of the output (with a truncation marker + full-file pointer in the
    middle), and the full content saved to a file.

    Keeping the tail is critical: for command output the most informative part is
    the end (test summary line, last error, exit code). A head-only truncation
    made the model miss the verdict of its own test runs. Split is ~1/3 head,
    ~2/3 tail by default.
    """
    lines = output.split("\n")
    total_lines = len(lines)

    if total_lines <= max_lines and len(output) <= max_chars:
        return output

    # Save full output to file
    out_dir = _get_output_dir()
    filename = f"{tool_name.lower()}_{int(time.time())}_{os.getpid()}.txt"
    saved_path = out_dir / filename
    saved_path.write_text(output, encoding="utf-8")

    # Truncation marker (regex-compatible with formatter.resolve_overflow_pointer,
    # which uses .search() — so placing it in the MIDDLE does not break parsing).
    msg = (
        f"\n\n[...output truncated — {total_lines} lines total, "
        f"full output saved to: {saved_path}]\n"
        f'[Use Read(file_path="{saved_path}") to see the complete output]\n\n'
    )

    # Entre max_lines et head+tail lignes (201-240 par défaut), l'ancienne version ajoutait le
    # marqueur SANS rien couper (T7 du rapport docs/reduction_tokens : 222 lignes, 12 285 car.
    # envoyés en entier). On ramène alors tête + queue à max_lines, dans la même proportion.
    if head_lines + tail_lines >= total_lines:
        head_lines = max_lines * head_lines // max(head_lines + tail_lines, 1)
        tail_lines = max_lines - head_lines
    if head_lines + tail_lines < total_lines:
        head = "\n".join(lines[:head_lines])
        tail = "\n".join(lines[total_lines - tail_lines:]) if tail_lines else ""
    else:  # peu de lignes mais trop de caractères : on coupe au caractère
        head = tail = output
    # Plafond de caractères appliqué dans tous les cas : 1/3 tête, le reste pour la queue.
    head = head[:max_chars // 3]
    tail = tail[len(tail) - (max_chars - len(head)):] if len(tail) > max_chars - len(head) else tail
    return head + msg + tail
