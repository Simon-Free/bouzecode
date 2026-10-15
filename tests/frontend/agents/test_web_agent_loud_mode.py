# [desc] Tests that web agents receive --loud and that no mode puts a <thinking> instruction in the system prompt [/desc]
"""Web agents are launched with --loud; neither loud nor extended mode asks for <thinking> text."""
from unittest.mock import patch, MagicMock
import subprocess

from bouzecode.backend.core.context import build_system_prompt


def test_system_prompt_without_loud_has_no_thinking_instructions():
    """Config with thinking=True but thinking_mode=extended should NOT have the <thinking> format instruction."""
    config = {"thinking": True, "thinking_mode": "extended"}
    prompt = build_system_prompt(config)
    assert "Mode Réflexion à Voix Haute" not in prompt
    assert "RÈGLES ABSOLUES" not in prompt


def test_system_prompt_with_loud_has_no_thinking_instructions():
    """The think-out-loud mode was removed: thinking_mode=loud adds nothing to the prompt."""
    config = {"thinking": True, "thinking_mode": "loud"}
    prompt = build_system_prompt(config)
    assert "Mode Réflexion à Voix Haute" not in prompt
    assert "<thinking>" not in prompt
    assert "RÈGLES ABSOLUES" not in prompt


def test_create_agent_includes_loud_flag():
    """create_agent() passes --loud (thinking on, same config on spawn/resume/wake)."""
    from bouzecode.web_v2.runtime.runner.agent_commande import _bouzecode_launch_cmd
    from bouzecode.web_v2.runtime.runner import agent_creation, agent_fiche

    # Patch subprocess.Popen to capture the command
    captured_cmd = []

    class FakePopen:
        pid = 99999
        def __init__(self, cmd, **kwargs):
            captured_cmd.extend(cmd)

    with patch.object(subprocess, "Popen", FakePopen):
        with patch.object(agent_fiche, "_save"):
            with patch("builtins.open", MagicMock()):
                agent_creation.create_agent("test prompt", "claude-sonnet-4-20250514", "/tmp")

    assert "--loud" in captured_cmd, f"--loud not found in command: {captured_cmd}"
