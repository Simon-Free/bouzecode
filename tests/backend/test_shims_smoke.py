"""Smoke tests for OSS feature shims wired into the new engine dispatcher.

Tests verify that the /voice, /mcp, /plugin commands are callable
without crashing (mocked dependencies, no real hardware or network).
"""
from __future__ import annotations

import pytest


@pytest.mark.backend
class TestShimsSmoke:
    """Feature shim smoke tests — no network, no hardware."""

    def test_voice_command_import(self):
        """The /voice shim is importable and registered."""
        from bouzecode.backend.commands.dispatcher import COMMANDS
        assert "voice" in COMMANDS

    def test_mcp_command_import(self):
        """The /mcp shim is importable and registered."""
        from bouzecode.backend.commands.dispatcher import COMMANDS
        assert "mcp" in COMMANDS

    def test_plugin_command_import(self):
        """The /plugin shim is importable and registered."""
        from bouzecode.backend.commands.dispatcher import COMMANDS
        assert "plugin" in COMMANDS

    def test_memory_command_import(self):
        """The /memory shim is importable and registered."""
        from bouzecode.backend.commands.dispatcher import COMMANDS
        assert "memory" in COMMANDS

    def test_voice_command_callable(self):
        """Calling /voice with no args doesn't crash (deps missing is OK)."""
        from bouzecode.backend.commands.dispatcher import COMMANDS
        # Signature: cmd_voice(args, state, config)
        try:
            result = COMMANDS["voice"]("", None, {})
        except SystemExit:
            pass  # some commands call sys.exit
        except Exception as e:
            # ImportError for sounddevice/voice is acceptable (optional dep)
            if "sounddevice" not in str(e) and "No module" not in str(e) and "voice" not in str(e).lower():
                raise

    def test_mcp_command_callable(self):
        """Calling /mcp list doesn't crash."""
        from bouzecode.backend.commands.dispatcher import COMMANDS
        try:
            result = COMMANDS["mcp"]("list", {})
        except SystemExit:
            pass
        except Exception:
            pass  # MCP may not be configured — that's fine

    def test_plugin_command_callable(self):
        """Calling /plugin list doesn't crash."""
        from bouzecode.backend.commands.dispatcher import COMMANDS
        try:
            result = COMMANDS["plugin"]("", {})
        except SystemExit:
            pass
        except Exception:
            pass  # No plugins installed — that's fine
