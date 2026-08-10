# [desc] Conversation feature tests: skills guidance reaches the model's system prompt, and Skill(name=) returns a rendered body. [/desc]
"""Skill behaviour observed through real bouzecode() conversations.

Replaces the prompt-content assertions of test_skills_section.py and
test_skill_loading_prompt.py (the "skills section / load BEFORE you act guidance is
in the built prompt" tests): instead of calling get_skills_section() directly, we
build the real system prompt and assert the guidance reaches the payload the model
sees (mock.recorded_calls[0]).

Also replaces the conversation-observable half of test_skills.py: instead of calling
find_skill()/substitute_arguments() in isolation, the (mocked) model emits a Skill
tool call and we assert on the rendered body that lands in the transcript.

Pure file parsing (_parse_skill_file, _parse_list_field) and load_skills() directory
discovery stay as units in test_skills.py — they are not conversation-observable.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.core.context import build_system_prompt_parts

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
# Closing reply: PLAIN TEXT, no tool call. A Methodology/Snippet-only batch is
# bookkeeping — since b83ade94 it never closes the session, it earns a
# continue-nudge. Only FinalAnswer or a tool-call-free reply closes.
CLOSE = "C'est fait."


# ── skills guidance reaches the model's system prompt ────────────────────────

def _payload_with_real_prompt(config_overrides=None):
    """Run one trivial turn with the REAL system prompt; return the payload string."""
    stable = build_system_prompt_parts(config_overrides or {})[0]
    mock = MockLLM(["Hi!"])
    bouzecode(["hi"], mock_llm=mock, system_prompt=stable,
              config_overrides=config_overrides)
    return str(mock.recorded_calls[0])


def test_skills_section_reaches_the_model_system_prompt():
    """Prompt V2: the SkillList/Skill discovery instruction reaches the wire
    (skills themselves are no longer listed in the prompt)."""
    payload = _payload_with_real_prompt()
    assert "SkillList()" in payload
    assert "Skill(name=" in payload


def test_load_project_config_rule_reaches_the_model():
    """The project-skills rule (LoadProjectConfig before acting) reaches the wire."""
    payload = _payload_with_real_prompt()
    assert "LoadProjectConfig" in payload


def test_load_aggressively_guidance_reaches_the_model():
    """The load-early/load-liberally guidance reaches the wire."""
    payload = _payload_with_real_prompt()
    assert "too many skills than too few" in payload
    assert "BEFORE" in payload


def test_thinking_prompt_skill_scanning_rule_reaches_the_model():
    """In loud-thinking mode, the 'scan the Skills' rule reaches the model's prompt."""
    payload = _payload_with_real_prompt({"thinking": True, "thinking_mode": "loud"})
    assert "Scanner les Skills" in payload
    assert "Skill(name=" in payload


# ── Skill(name=) returns a rendered body into the transcript ─────────────────

def _tool_result(result, name):
    msgs = [m for m in result.messages if m.get("role") == "tool" and m.get("name") == name]
    assert msgs, f"no {name} tool result in transcript"
    return msgs[0]["content"]


def _invoke_skill(name, args=""):
    """Drive a Skill(name=) through a conversation; return the Skill tool result.

    Skill is snippetable, so turn 2 emits Snippet(discard) to satisfy enforcement."""
    args_xml = f'<param name="args">{args}</param>' if args else ""
    call = (f'<tool_use name="Skill" id="sk1"><param name="name">{name}</param>'
            f'{args_xml}</tool_use>')
    snip = '<tool_use name="Snippet" id="s1"><param name="discard">true</param></tool_use>'
    mock = MockLLM([f"{METH}\n{call}", f"{METH}\n{snip}", CLOSE])
    result = bouzecode([f"use {name}"], mock_llm=mock)
    return _tool_result(result, "Skill")


def test_skill_invocation_returns_builtin_body():
    """Invoking the builtin 'commit' skill returns its rendered prompt body."""
    out = _invoke_skill("commit")
    assert "[Skill: commit" in out
    assert "commit" in out.lower()


def test_skill_invocation_unknown_lists_available():
    """An unknown skill errors and lists available skills so the model can recover."""
    out = _invoke_skill("does-not-exist-xyz")
    assert "not found" in out
    assert "Available:" in out
    assert "commit" in out  # a builtin is listed


def test_skill_invocation_trigger_alias_resolves():
    """A /trigger alias resolves to the skill (find_skill fallback) and returns its body."""
    out = _invoke_skill("/review")
    assert "[Skill: review" in out


def test_skill_invocation_substitutes_arguments():
    """Args passed to Skill replace $ARGUMENTS in the rendered body (substitute_arguments)."""
    out = _invoke_skill("review", args="PR-12345")
    assert "PR-12345" in out
    assert "$ARGUMENTS" not in out
