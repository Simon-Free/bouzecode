# [desc] Conversation feature tests: a project .bouzecode/ skill (auto-loaded or via LoadProjectConfig) becomes discoverable through SkillResearch. [/desc]
"""Project-config auto-loading observed through real bouzecode() conversations.

Skills are listed neither in the system prompt nor in the LoadProjectConfig briefing —
the model finds them by calling SkillResearch(query=...). So registration is asserted on
the SkillResearch tool result the model receives, not on the prompt payload.

Two entry points are exercised, both conversation-observable:
  - auto-load: cwd has .bouzecode/skills/<name> → register_extra_dirs at startup →
    SkillResearch() returns the skill.
  - LoadProjectConfig: the (mocked) model calls the tool mid-conversation; a
    SkillResearch() call on the next turn finds the freshly-registered skill.

The pure registry mechanics (dedup, replace, copy-on-read) stay as units in
test_paths.py; the briefing itself (designated / unknown / dismissed folders, plugins,
cd) is covered by tests/backend/tools/test_load_project_config.py.
"""
from __future__ import annotations

import os

import pytest

import bouzecode.backend.core.paths as _paths
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
# Closing reply: PLAIN TEXT, no tool call. A Methodology/Snippet-only batch is
# bookkeeping — since b83ade94 it never closes the session, it earns a
# continue-nudge. Only FinalAnswer or a tool-call-free reply closes.
CLOSE = "C'est fait."

SKILL_MD = (
    "---\nname: custom-deploy\ndescription: Deploy to the custom staging env\n---\n"
    "Deploy steps here\n"
)

RESEARCH_CALL = ('<tool_use name="SkillResearch" id="sr1">'
                 '<param name="query">staging deploy</param></tool_use>')


@pytest.fixture(autouse=True)
def _reset_extra_dirs():
    _paths._extra_dirs = []
    yield
    _paths._extra_dirs = []


def _make_project_skill(tmp_path):
    """Create tmp_path/.bouzecode/skills/custom_deploy.md and return the project root."""
    skills_dir = tmp_path / ".bouzecode" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "custom_deploy.md").write_text(SKILL_MD, encoding="utf-8")
    return tmp_path


def _tool_result(result, name: str) -> str:
    return next(m["content"] for m in result.messages
                if m.get("role") == "tool" and m.get("name") == name)


def _research_result():
    """Run a conversation whose model calls SkillResearch(); return the tool result."""
    mock = MockLLM([f"{METH}\n{RESEARCH_CALL}", CLOSE])
    return _tool_result(bouzecode(["which skill deploys to staging?"], mock_llm=mock), "SkillResearch")


# ── auto-load: .bouzecode/ in cwd → skill discoverable via SkillResearch ─────

def test_autoloaded_project_skill_reaches_the_model(tmp_path, monkeypatch):
    """A skill in cwd/.bouzecode/skills is found by the SkillResearch() the model calls."""
    project = _make_project_skill(tmp_path)
    monkeypatch.chdir(project)

    # Startup auto-load logic: register cwd/.bouzecode as an extra dir.
    _paths.register_extra_dirs([os.path.abspath(".bouzecode")])

    found = _research_result()
    assert "custom-deploy — Deploy to the custom staging env" in found


def test_no_project_skill_not_found(tmp_path, monkeypatch):
    """With no .bouzecode/ registered, the custom skill is absent from SkillResearch()."""
    monkeypatch.chdir(tmp_path)
    assert "custom-deploy" not in _research_result()


# ── LoadProjectConfig: tool call mid-conversation makes the skill findable ───

def test_load_project_config_makes_skill_findable_next_turn(tmp_path, monkeypatch):
    """Model calls LoadProjectConfig → the project's skill is found by SkillResearch next turn.

    The briefing itself only COUNTS the skills and points at SkillResearch: the skill's
    description must reach the model through the search, not through the briefing.
    """
    project = _make_project_skill(tmp_path)
    monkeypatch.chdir(project)

    call = (f'<tool_use name="LoadProjectConfig" id="lpc1">'
            f'<param name="path">{project}</param></tool_use>')
    mock = MockLLM([f"{METH}\n{call}", f"{METH}\n{RESEARCH_CALL}", CLOSE])
    result = bouzecode(["load my project"], mock_llm=mock)

    briefing = _tool_result(result, "LoadProjectConfig")
    assert "équipé" in briefing
    assert "1 skill de projet disponible" in briefing
    assert "SkillResearch(query=" in briefing
    assert "Deploy to the custom staging env" not in briefing

    found = _tool_result(result, "SkillResearch")
    assert "custom-deploy — Deploy to the custom staging env" in found


def test_load_project_config_missing_dir_reports_error(tmp_path):
    """Calling LoadProjectConfig on a folder that does not exist yields a clean error."""
    missing = tmp_path / "nulle-part"
    call = (f'<tool_use name="LoadProjectConfig" id="lpc1">'
            f'<param name="path">{missing}</param></tool_use>')
    mock = MockLLM([f"{METH}\n{call}", CLOSE])
    result = bouzecode(["load it"], mock_llm=mock)

    assert "dossier introuvable" in _tool_result(result, "LoadProjectConfig")
