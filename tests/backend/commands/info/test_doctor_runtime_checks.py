# [desc] /doctor really checks ripgrep and the tool registry, as the README promises. [/desc]
"""`/doctor` claims to diagnose "interpreter, key, rg, tool registry".

It checked the interpreter, git and the key — and neither `rg` nor the registry.
Both matter: without ripgrep every Grep/Glob falls back to a Python tree walk,
and without a populated registry the agent has no tools at all.
"""
from __future__ import annotations

import shutil

from bouzecode.backend.commands.info.runtime_checks import (
    ESSENTIAL_TOOLS,
    ripgrep_status,
    tool_registry_status,
)
from bouzecode.backend.core.tool_registry import disable_tool, enable_tool

_LEVELS = ("pass", "warn", "fail")


def test_ripgrep_is_reported_one_way_or_the_other():
    level, message = ripgrep_status()

    assert level in _LEVELS
    assert "ripgrep" in message
    if shutil.which("rg"):
        assert level == "pass"
    else:
        assert level == "warn" and "fall back" in message


def test_a_healthy_registry_passes_and_counts_its_tools():
    level, message = tool_registry_status()

    assert level == "pass", message
    assert "registered" in message and "offered" in message


def test_a_disabled_essential_tool_is_reported():
    """Disabling Read must not stay invisible: it is how the agent sees the code."""
    disable_tool("Read")
    try:
        level, message = tool_registry_status()
    finally:
        enable_tool("Read")

    assert level == "warn"
    assert "Read" in message


def test_the_essentials_are_the_tools_an_agent_cannot_work_without():
    assert set(ESSENTIAL_TOOLS) == {"Read", "Bash", "Methodology", "FinalAnswer"}


def test_doctor_renders_both_checks(capsys):
    """The command itself, end to end: both lines reach the user's screen."""
    from bouzecode.backend.commands.info.diagnostics import cmd_doctor

    class BareState:
        turn_count = 0
        messages: list = []

    cmd_doctor("", BareState(), {"model": "claude-opus-4-8", "anthropic_api_key": ""})
    printed = capsys.readouterr().out

    assert "ripgrep" in printed
    assert "Tool registry" in printed
