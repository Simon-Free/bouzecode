# [desc] Tests that Snippet documentation and tool schema mention Skill as a trigger source alongside Read [/desc]
"""Test that Snippet documentation mentions Skill as a trigger."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def test_system_prompt_mentions_skill_in_snippet_rule():
    """The system prompt must tell the model to Snippet Skill results too.
    V3 wording (audit du prompt, 2026-09-24) : la règle vise tout résultat marqué
    « A SNIPPETER » et nomme `Read` et `Skill` en exemples, sur la même ligne."""
    content = (PROJECT_ROOT / "src" / "system_prompts" / "01_main_system_prompt.txt").read_text(encoding="utf-8")
    rule = next(line for line in content.splitlines() if "A SNIPPETER" in line)
    assert "`Snippet`" in rule and "`Read`" in rule and "`Skill`" in rule


def test_snippet_tool_description_mentions_skill():
    """The Snippet tool schema must list Skill among trigger sources."""
    content = (PROJECT_ROOT / "src" / "bouzecode" / "backend" / "tools" / "schemas.py").read_text(encoding="utf-8")
    # L'énumération ne cite que des outils que TOUS les profils ont : GetFolderDescription
    # et WebFetch en sont sortis (absents de plusieurs profils) — cf. conformité prompt/registre.
    # Grep en est sorti le 2026-09-24 : son résultat n'est pas marqué « A SNIPPETER »
    # (snippet_wire._FILE_SNIPPET_TOOLS = Read/Skill/Edit/Write), la règle mentait.
    assert "Read/Skill" in content
