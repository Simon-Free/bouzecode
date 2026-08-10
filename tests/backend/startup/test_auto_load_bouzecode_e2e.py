# [desc] Conversation feature tests: a project .bouzecode/ skill (auto-loaded or via LoadProjectConfig) becomes discoverable through SkillList. [/desc]
"""Project-config auto-loading observed through real bouzecode() conversations.

Prompt V2 (4235c23/dc56090): skills are no longer LISTED in the system prompt —
the model discovers them by calling SkillList(). So registration is asserted on
the SkillList tool result the model receives, not on the prompt payload.

Two entry points are exercised, both conversation-observable:
  - auto-load: cwd has .bouzecode/skills/<name> → register_extra_dirs at startup →
    SkillList() returns the skill.
  - LoadProjectConfig: the (mocked) model calls the tool mid-conversation; a
    SkillList() call on the next turn sees the freshly-registered skill.

The pure registry mechanics (dedup, replace, copy-on-read) stay as units in
test_paths.py; the granular .bouzecode-tree parsing (MCP/plugin/hook discovery counts,
malformed JSON) stays in test_project_config.py — those are not conversation-observable.
"""
from __future__ import annotations

import os

import pytest

import bouzecode.backend.core.paths as _paths
from bouzecode.backend.core.context import build_system_prompt_parts
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


SKILLLIST_CALL = '<tool_use name="SkillList" id="sl1"></tool_use>'


def _skilllist_result():
    """Run a conversation whose model calls SkillList(); return the tool result."""
    mock = MockLLM([f"{METH}\n{SKILLLIST_CALL}", CLOSE])
    result = bouzecode(["what skills do you have?"], mock_llm=mock)
    return next(m["content"] for m in result.messages
                if m.get("role") == "tool" and m.get("name") == "SkillList")


# ── auto-load: .bouzecode/ in cwd → skill discoverable via SkillList ─────────

def test_autoloaded_project_skill_reaches_the_model(tmp_path, monkeypatch):
    """A skill in cwd/.bouzecode/skills shows up in the SkillList() the model receives."""
    project = _make_project_skill(tmp_path)
    monkeypatch.chdir(project)

    # Startup auto-load logic: register cwd/.bouzecode as an extra dir.
    _paths.register_extra_dirs([os.path.abspath(".bouzecode")])

    listing = _skilllist_result()
    assert "custom-deploy" in listing
    assert "Deploy to the custom staging env" in listing


def test_no_project_skill_not_in_prompt(tmp_path, monkeypatch):
    """With no .bouzecode/ registered, the custom skill is absent from SkillList()."""
    monkeypatch.chdir(tmp_path)
    assert "custom-deploy" not in _skilllist_result()


# ── LoadProjectConfig: tool call mid-conversation injects the skill ──────────

def test_load_project_config_injects_skill_into_next_turn(tmp_path, monkeypatch):
    """Model calls LoadProjectConfig → the project's skill is discoverable next turn.

    Turn 1: model calls LoadProjectConfig(path=project) (real tool runs, registers the
    extra dir). Then a SkillList() call sees the freshly-registered skill — proving the
    registration is observable to the model on the following turn.
    """
    project = _make_project_skill(tmp_path)
    # Work from the project dir: LoadProjectConfig(path=project) is the "I'm working in
    # this project, load its config" scenario. Skill discovery is relative to cwd
    # (loader._get_skill_paths scans _project_skill_dirs(cwd)), so the model must be
    # running inside the project for its .bouzecode/skills to reach the next SkillList.
    monkeypatch.chdir(project)

    # Turn 1: LoadProjectConfig registers the extra dir. Turn 2: SkillList sees the
    # freshly-registered skill — proving the registration is observable to the model
    # on the FOLLOWING TURN of the SAME conversation (not via a separate run).
    call = (f'<tool_use name="LoadProjectConfig" id="lpc1">'
            f'<param name="path">{project}</param></tool_use>')
    mock = MockLLM([f"{METH}\n{call}", f"{METH}\n{SKILLLIST_CALL}", CLOSE])
    result = bouzecode(["load my project"], mock_llm=mock)

    # The tool result confirms registration happened in-conversation.
    tool_msgs = [m for m in result.messages
                 if m.get("role") == "tool" and m.get("name") == "LoadProjectConfig"]
    assert tool_msgs, "no LoadProjectConfig tool result in transcript"
    assert "Registered" in tool_msgs[0]["content"]

    # The SkillList() called on the NEXT turn (same conversation) sees the skill.
    listing = next(m["content"] for m in result.messages
                   if m.get("role") == "tool" and m.get("name") == "SkillList")
    assert "custom-deploy" in listing
    assert "Deploy to the custom staging env" in listing


def test_load_project_config_missing_dir_reports_error(tmp_path):
    """Calling LoadProjectConfig on a dir with no .bouzecode/ yields a clean error."""
    call = (f'<tool_use name="LoadProjectConfig" id="lpc1">'
            f'<param name="path">{tmp_path}</param></tool_use>')
    mock = MockLLM([f"{METH}\n{call}", CLOSE])
    result = bouzecode(["load it"], mock_llm=mock)

    tool_msgs = [m for m in result.messages
                 if m.get("role") == "tool" and m.get("name") == "LoadProjectConfig"]
    assert tool_msgs, "no LoadProjectConfig tool result in transcript"
    assert "Error" in tool_msgs[0]["content"]
    assert ".bouzecode/" in tool_msgs[0]["content"]
