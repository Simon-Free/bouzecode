# [desc] Tests that Snippet documentation references Skill as a trigger in system prompt and tool schema
# <tool_use name="FinalAnswer" id="r1"><param name="answer">Tests that Snippet documentation references Skill as a trigger in system prompt and tool schema</param></tool_use> [/desc]
"""Test that Snippet documentation mentions Skill as a trigger."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def test_system_prompt_mentions_skill_in_snippet_rule():
    """The system prompt must tell the model to Snippet Skill results too.
    V2 wording (dc56090): '`Snippet` — un par `Read`/`Skill` reçu'."""
    content = (PROJECT_ROOT / "src" / "system_prompts" / "01_main_system_prompt.txt").read_text(encoding="utf-8")
    assert "un par `Read`/`Skill` reçu" in content


def test_snippet_tool_description_mentions_skill():
    """The Snippet tool schema must list Skill among trigger sources."""
    content = (PROJECT_ROOT / "src" / "bouzecode" / "backend" / "tools" / "schemas.py").read_text(encoding="utf-8")
    assert "Read/Skill/Grep/GetFolderDescription/WebFetch" in content
