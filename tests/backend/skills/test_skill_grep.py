"""Tests for SkillGrep's pure grep function (no mocks, hand-built SkillDefs)."""
from __future__ import annotations

from bouzecode.backend.tools.skill.loader import SkillDef
from bouzecode.backend.tools.skill.tools import _grep_skills


def _skill(name: str, prompt: str, file_path: str = "/skills/x.md") -> SkillDef:
    return SkillDef(
        name=name,
        description="desc",
        triggers=[],
        tools=[],
        prompt=prompt,
        file_path=file_path,
    )


def test_grep_matches_content_and_reports_lines():
    skills = [
        _skill("commit", "line one\nrun git commit here\nline three", "/skills/commit.md"),
        _skill("review", "review the diff\nno match word", "/skills/review.md"),
    ]

    out = _grep_skills(skills, r"git commit")

    assert "**commit**" in out
    assert "/skills/commit.md" in out
    assert "run git commit here" in out
    # The non-matching skill must not appear.
    assert "**review**" not in out


def test_grep_reports_all_matching_lines_within_a_skill():
    skills = [_skill("multi", "alpha token\nbeta\ngamma token", "/skills/m.md")]

    out = _grep_skills(skills, "token")

    assert "alpha token" in out
    assert "gamma token" in out
    assert "beta" not in out


def test_grep_is_case_insensitive_by_default():
    skills = [_skill("c", "HELLO world", "/skills/c.md")]

    out = _grep_skills(skills, "hello")

    assert "**c**" in out


def test_grep_case_sensitive_when_disabled():
    skills = [_skill("c", "HELLO world", "/skills/c.md")]

    out = _grep_skills(skills, "hello", ignore_case=False)

    assert "No skills matched" in out


def test_grep_no_match_returns_message():
    skills = [_skill("c", "nothing here", "/skills/c.md")]

    out = _grep_skills(skills, "absent-pattern")

    assert "No skills matched" in out


def test_grep_invalid_regex_returns_error():
    skills = [_skill("c", "content", "/skills/c.md")]

    out = _grep_skills(skills, "[unclosed")

    assert "Invalid regex" in out or "invalid" in out.lower()


def test_grep_searches_full_file_content_including_frontmatter(tmp_path):
    # Real .md file with YAML frontmatter; the parsed prompt body does NOT
    # contain "name: foo" — only the raw file does. Grep must find it.
    md = tmp_path / "foo.md"
    md.write_text("---\nname: foo\ndescription: bar baz\n---\nprompt body here\n", encoding="utf-8")
    s = _skill("foo", prompt="prompt body here", file_path=str(md))

    out = _grep_skills([s], "name: foo")

    assert "**foo**" in out
    assert "name: foo" in out
