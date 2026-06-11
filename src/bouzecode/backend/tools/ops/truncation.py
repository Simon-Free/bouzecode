# [desc] Helper to truncate large tool outputs and save full content to a readable file for later access. [/desc]
from __future__ import annotations

import os
import re
import time
from pathlib import Path


def _get_output_dir() -> Path:
    """Return directory for saved tool outputs."""
    custom = os.environ.get("BOUZECODE_TOOL_OUTPUT_DIR")
    if custom:
        d = Path(custom)
    else:
        d = Path.home() / ".bouzecode" / "tool_outputs"
    d.mkdir(parents=True, exist_ok=True)
    return d


_PYTEST_SUMMARY_RE = re.compile(
    r"^=+ .*(passed|failed|error|skipped|warning|deselected).* in [\d.]+s.*=+$"
)
_PYTEST_SECTION_RE = re.compile(r"^=+ (FAILURES|ERRORS|warnings summary|short test summary info) =+$")
_PYTEST_PROGRESS_RE = re.compile(r"^.+\.(py|pyx)::\S+.*(?:PASSED|FAILED|ERROR)|^.+\.py\s+[.FEsx]+\s+\[\s*\d+%\]")


def compact_pytest_output(output: str) -> str:
    """Compact pytest output, preserving failures/errors/warnings and summary.

    If the output does not look like pytest output, return it unchanged.
    """
    lines = output.split("\n")

    # Detect pytest output by looking for the summary line
    summary_line = None
    summary_idx = -1
    for i, line in enumerate(lines):
        if _PYTEST_SUMMARY_RE.match(line.strip()):
            summary_line = line
            summary_idx = i

    # Also check for "test session starts" header
    has_session_start = any("test session starts" in l for l in lines[:10])

    if summary_line is None and not has_session_start:
        # Not pytest output
        return output

    # Parse sections: find FAILURES, ERRORS, warnings summary, short test summary
    sections: list[tuple[str, int, int]] = []  # (name, start, end)
    i = 0
    while i < len(lines):
        line_stripped = lines[i].strip()
        m = _PYTEST_SECTION_RE.match(line_stripped)
        if m:
            section_name = m.group(1)
            section_start = i
            # Find end of section (next === line that's not part of this section)
            j = i + 1
            while j < len(lines):
                if _PYTEST_SUMMARY_RE.match(lines[j].strip()):
                    break
                if _PYTEST_SECTION_RE.match(lines[j].strip()):
                    break
                j += 1
            sections.append((section_name, section_start, j))
            i = j
        else:
            i += 1

    # Determine if all green (no FAILURES or ERRORS section, summary has no "failed"/"error")
    has_failures = any(s[0] in ("FAILURES", "ERRORS") for s in sections)

    # Build compacted output
    result_parts: list[str] = []

    if has_failures:
        # Keep FAILURES, ERRORS, short test summary info sections integrally
        for section_name, start, end in sections:
            if section_name in ("FAILURES", "ERRORS", "short test summary info", "warnings summary"):
                result_parts.append("\n".join(lines[start:end]))
    else:
        # All green - check for warnings
        for section_name, start, end in sections:
            if section_name == "warnings summary":
                result_parts.append("\n".join(lines[start:end]))

        # If verbose output with <20 tests, list the test names
        verbose_tests = []
        for line in lines:
            if "PASSED" in line and "::" in line:
                # Extract test name from verbose line like "tests/test_a.py::test_one PASSED"
                parts = line.strip().split()
                if parts:
                    test_path = parts[0]
                    verbose_tests.append(test_path)
        if 0 < len(verbose_tests) <= 20:
            result_parts.append("Tests passed:")
            for t in verbose_tests:
                result_parts.append(f"  {t}")

    # Always append the summary line
    if summary_line:
        result_parts.append(summary_line.strip())

    if not result_parts:
        # Fallback: just return summary
        return summary_line.strip() if summary_line else output

    return "\n".join(result_parts)


def truncate_tool_output(
    output: str,
    tool_name: str,
    max_lines: int = 200,
    max_chars: int = 8000,
    head_lines: int = 80,
) -> str:
    """Truncate output if it exceeds thresholds, saving full output to a file.

    Returns the original output if under thresholds, or the head + truncation
    message with a path to the full saved file.
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

    # Return head + truncation message
    head = "\n".join(lines[:head_lines])
    msg = (
        f"\n\n[...output truncated — {total_lines} lines total, "
        f"full output saved to: {saved_path}]\n"
        f'[Use Read(file_path="{saved_path}") to see the complete output]'
    )
    return head + msg
