# [desc] Regression test failing if any src comment line contains leaked tool-call XML markup. [/desc]
"""Regression guard for corrupted `[desc]` headers.

A generation bug once incrusted tool-call XML markup into the leading
`# [desc] ... [/desc]` comment of several source files. This test walks every
`.py` file under src/ and fails if a `[desc]` header comment line contains
emitted tool markup: `<tool_use name=`, `</tool_use>` or `<param name=`.

It intentionally only inspects `[desc]` comment lines, and only these three
concrete markers (the markup that is actually EMITTED). Descriptive comments
that legitimately mention `<tool_use>` (e.g. the xml_tool_protocol parser's own
header, or html_renderer regex comments) are NOT flagged, so protocol modules
stay green while any corrupted `[desc]` header fails the test.
"""
from pathlib import Path

FORBIDDEN = ('<tool_use name=', '</tool_use>', '<param name=')

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "bouzecode"


def _offending_lines(path: Path) -> list[str]:
    offenders = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip().startswith("#"):
            continue
        if "[desc]" not in raw:
            continue
        if any(marker in raw for marker in FORBIDDEN):
            offenders.append(f"{path}:{lineno}: {raw.strip()}")
    return offenders


def test_no_leaked_tool_markup_in_comments():
    all_offenders = []
    for py in sorted(SRC_ROOT.rglob("*.py")):
        all_offenders.extend(_offending_lines(py))

    assert not all_offenders, (
        "Leaked tool-call markup found in code comments (a corrupted [desc] header?). "
        "Keep only the plain description text, drop the XML markup:\n"
        + "\n".join(all_offenders)
    )
