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

_REPO_ROOT = Path(__file__).resolve().parents[2]
# Both trees: the corruption hit test files as often as sources, and a `[desc]`
# header spanning several comment lines hid the markup on the CONTINUATION line,
# which a check keyed on `[desc]` being present on the same line never saw.
SCANNED_ROOTS = (_REPO_ROOT / "src" / "bouzecode", _REPO_ROOT / "tests")


def _offending_lines(path: Path) -> list[str]:
    """Scan the leading `# [desc] … [/desc]` comment block, however many lines it spans."""
    offenders = []
    in_header = False
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip().startswith("#"):
            if in_header:
                break
            continue
        if "[desc]" in raw:
            in_header = True
        if not in_header:
            continue
        if any(marker in raw for marker in FORBIDDEN):
            offenders.append(f"{path}:{lineno}: {raw.strip()}")
        if "[/desc]" in raw:
            break
    return offenders


def test_no_leaked_tool_markup_in_comments():
    all_offenders = []
    for root in SCANNED_ROOTS:
        for py in sorted(root.rglob("*.py")):
            all_offenders.extend(_offending_lines(py))

    assert not all_offenders, (
        "Leaked tool-call markup found in code comments (a corrupted [desc] header?). "
        "Keep only the plain description text, drop the XML markup:\n"
        + "\n".join(all_offenders)
    )
