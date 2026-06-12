"""E2E tests for /voice command — STT and recorder fully mocked (no hardware, no network)."""
from __future__ import annotations

import sys
import types
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_cmd_voice():
    """Import cmd_voice from oss_shims."""
    from bouzecode.backend.commands.oss_shims.voice_cmd import cmd_voice
    return cmd_voice


def _make_state():
    """Minimal state-like object (unused by voice shim but required by dispatcher sig)."""
    return types.SimpleNamespace()


def _make_config(**overrides):
    """Minimal config dict."""
    cfg = {"voice_language": "fr", "voice_max_seconds": 15}
    cfg.update(overrides)
    return cfg


# ---------------------------------------------------------------------------
# Tests: successful voice flow
# ---------------------------------------------------------------------------

class TestVoiceRecord:
    """Test /voice default (record + transcribe) with mocked voice package."""

    def test_voice_returns_sentinel_with_transcribed_text(self, monkeypatch):
        """When voice_input returns text, cmd_voice returns ('__voice__', text)."""
        # Mock the voice package functions
        monkeypatch.setattr(
            "voice.check_voice_deps", lambda: (True, None), raising=False
        )
        monkeypatch.setattr(
            "voice.voice_input",
            lambda language="auto", max_seconds=30, **kw: "bonjour le monde",
            raising=False,
        )

        cmd_voice = _get_cmd_voice()
        result = cmd_voice("", _make_state(), _make_config())

        assert result == ("__voice__", "bonjour le monde")

    def test_voice_passes_config_language_and_max_seconds(self, monkeypatch):
        """Config values are forwarded to voice_input."""
        captured = {}

        def mock_voice_input(language="auto", max_seconds=30, **kw):
            captured["language"] = language
            captured["max_seconds"] = max_seconds
            return "test text"

        monkeypatch.setattr("voice.check_voice_deps", lambda: (True, None), raising=False)
        monkeypatch.setattr("voice.voice_input", mock_voice_input, raising=False)

        cmd_voice = _get_cmd_voice()
        cmd_voice("", _make_state(), _make_config(voice_language="en", voice_max_seconds=60))

        assert captured["language"] == "en"
        assert captured["max_seconds"] == 60

    def test_voice_empty_transcription_returns_none(self, monkeypatch):
        """When voice_input returns empty string, cmd_voice returns None."""
        monkeypatch.setattr("voice.check_voice_deps", lambda: (True, None), raising=False)
        monkeypatch.setattr("voice.voice_input", lambda **kw: "", raising=False)

        cmd_voice = _get_cmd_voice()
        result = cmd_voice("", _make_state(), _make_config())

        assert result is None

    def test_voice_recording_exception_returns_none(self, monkeypatch):
        """When voice_input raises, cmd_voice returns None gracefully."""
        monkeypatch.setattr("voice.check_voice_deps", lambda: (True, None), raising=False)

        def mock_voice_input(**kw):
            raise RuntimeError("PortAudio device not found")

        monkeypatch.setattr("voice.voice_input", mock_voice_input, raising=False)

        cmd_voice = _get_cmd_voice()
        result = cmd_voice("", _make_state(), _make_config())

        assert result is None


# ---------------------------------------------------------------------------
# Tests: /voice status
# ---------------------------------------------------------------------------

class TestVoiceStatus:
    """Test /voice status subcommand."""

    def test_status_deps_available(self, monkeypatch, capsys):
        """When deps are available, prints success message."""
        monkeypatch.setattr("voice.check_voice_deps", lambda: (True, None), raising=False)

        cmd_voice = _get_cmd_voice()
        result = cmd_voice("status", _make_state(), _make_config())

        assert result is None  # status never returns sentinel

    def test_status_deps_unavailable(self, monkeypatch, capsys):
        """When deps are missing, prints warning."""
        monkeypatch.setattr(
            "voice.check_voice_deps",
            lambda: (False, "No audio recording backend found."),
            raising=False,
        )

        cmd_voice = _get_cmd_voice()
        result = cmd_voice("status", _make_state(), _make_config())

        assert result is None


# ---------------------------------------------------------------------------
# Tests: dependencies missing
# ---------------------------------------------------------------------------

class TestVoiceDepsMissing:
    """Test behavior when voice package or its deps are not installed."""

    def test_voice_package_not_installed(self, monkeypatch):
        """When voice package is not importable, returns None with warning."""
        # Remove voice from sys.modules and make it unimportable
        monkeypatch.delitem(sys.modules, "voice", raising=False)
        monkeypatch.delitem(sys.modules, "voice.check_voice_deps", raising=False)

        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "voice" or name.startswith("voice."):
                raise ImportError("No module named 'voice'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        cmd_voice = _get_cmd_voice()
        result = cmd_voice("", _make_state(), _make_config())

        assert result is None

    def test_voice_deps_check_fails(self, monkeypatch):
        """When check_voice_deps returns unavailable, returns None."""
        monkeypatch.setattr(
            "voice.check_voice_deps",
            lambda: (False, "No STT backend available."),
            raising=False,
        )

        cmd_voice = _get_cmd_voice()
        result = cmd_voice("", _make_state(), _make_config())

        assert result is None


# ---------------------------------------------------------------------------
# Tests: sentinel integration with dispatcher
# ---------------------------------------------------------------------------

class TestVoiceDispatcherIntegration:
    """Test that /voice integrates correctly with the dispatcher sentinel flow."""

    def test_voice_registered_in_oss_commands(self):
        """cmd_voice is registered in OSS_COMMANDS under 'voice' key."""
        from bouzecode.backend.commands.oss_shims import OSS_COMMANDS
        assert "voice" in OSS_COMMANDS
        assert OSS_COMMANDS["voice"] is _get_cmd_voice()

    def test_sentinel_tuple_format(self, monkeypatch):
        """Return value matches expected sentinel format for REPL."""
        monkeypatch.setattr("voice.check_voice_deps", lambda: (True, None), raising=False)
        monkeypatch.setattr("voice.voice_input", lambda **kw: "hello world", raising=False)

        cmd_voice = _get_cmd_voice()
        result = cmd_voice("", _make_state(), _make_config())

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0] == "__voice__"
        assert isinstance(result[1], str)
        assert len(result[1]) > 0
