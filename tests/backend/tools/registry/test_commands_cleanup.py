"""Test that commands/ cleanup is correct: removed commands gone, new fused commands work."""
import types


def _mock_state():
    state = types.SimpleNamespace(
        messages=[],
        turn_count=0,
        user_loop_count=0,
        total_input_tokens=0,
        total_output_tokens=0,
        total_cache_read_tokens=0,
        total_cache_creation_tokens=0,
        distinct_base=0,
        timing_entries=[],
        conversation_start=0.0,
        compaction_log=[],
        context_state=types.SimpleNamespace(notes={}),
        notes_timeline=[],
        thinking_log=[],
        total_tool_calls=0,
    )
    return state


def _mock_config():
    return {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 8192,
        "permission_mode": "auto",
        "_session_id": "test123",
    }


EXPECTED_COMMANDS = {
    "help", "clear", "model", "config", "save", "load",
    "verbose", "thinking", "permissions", "cwd",
    "skills", "agents", "agent", "agent-upgrade", "tasks", "task",
    "checkpoint", "rewind", "revert", "plan",
    "compact", "init", "export", "copy", "diff",
    "doctor", "exit", "quit",
    "resume", "where", "tools",
    "history", "context", "cost", "timing",
    # `telegram` was listed as REMOVED, but nothing had been removed: the module,
    # its wiring in the agent loop (tools/interaction.py) and tests/test_telegram_e2e.py
    # were all still there — only the COMMANDS entry was missing, which made the
    # command unreachable rather than absent.
    "telegram",
    # Same story, same fix: `worker`, `ssj` and `image` were imported by dispatcher.py,
    # their sentinels were already listed in `_REPL_SENTINELS` and handled by
    # ui/repl_sentinels.py — only the COMMANDS entry was missing. Exercised end to end
    # in tests/backend/commands/sentinels/.
    "worker", "ssj", "image",
}

# Commands this (public) repo adds back on top of the engine: the OSS shims in
# `commands/oss_shims/` route them to the flat top-level packages.
OSS_SHIM_COMMANDS = {"voice", "mcp", "plugin", "memory", "video", "video-wizard"}

# `img` was an alias of `/image` in the old flat dispatcher and was not brought back:
# one name per command. `brainstorm` and `status` have no module here at all.
REMOVED_COMMANDS = {"brainstorm", "status", "img"}


def test_commands_import():
    from bouzecode.backend.commands.dispatcher import COMMANDS
    assert isinstance(COMMANDS, dict)


def test_commands_expected_keys():
    from bouzecode.backend.commands.dispatcher import COMMANDS
    assert set(COMMANDS.keys()) == EXPECTED_COMMANDS | OSS_SHIM_COMMANDS


def test_commands_removed_keys():
    from bouzecode.backend.commands.dispatcher import COMMANDS
    for cmd in REMOVED_COMMANDS:
        assert cmd not in COMMANDS, f"'{cmd}' should have been removed"


def test_cmd_info_import():
    from bouzecode.backend.commands.info import cmd_info
    assert callable(cmd_info)


def test_cmd_doctor_import():
    from bouzecode.backend.commands.info import cmd_doctor
    assert callable(cmd_doctor)


def test_handle_slash_import():
    from bouzecode.backend.commands import handle_slash
    assert callable(handle_slash)


def test_handle_slash_help():
    from bouzecode.backend.commands import handle_slash
    state = _mock_state()
    config = _mock_config()
    result = handle_slash("/help", state, config)
    assert result is True


def test_handle_slash_unknown():
    from bouzecode.backend.commands import handle_slash
    state = _mock_state()
    config = _mock_config()
    result = handle_slash("/brainstorm", state, config)
    # Unknown command returns True (error printed, but handled)
    assert result is True


def test_no_removed_files_importable():
    """Removed modules should not be importable."""
    import importlib

    import pytest

    for mod_name in ("bouzecode.backend.commands._personas",
                     "bouzecode.backend.commands.brainstorm"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(mod_name)
