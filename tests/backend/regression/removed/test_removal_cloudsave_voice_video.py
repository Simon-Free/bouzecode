# [desc] Tests verifying cloudsave, voice, and video features are fully removed from codebase [/desc]
"""Tests verifying cloudsave, voice, and video features are fully removed."""
import pytest


def test_removed_commands_absent_from_dispatcher():
    from bouzecode.backend.commands.dispatcher import COMMANDS, _CMD_META

    # `voice` / `video` are NOT removed in this (public) repo: they are wired on
    # purpose by `commands/oss_shims/` to the flat `voice/` and `video/` packages.
    # Only cloudsave is genuinely gone from the command surface.
    removed = {"cloudsave"}
    for cmd in removed:
        assert cmd not in COMMANDS, f"{cmd} still in COMMANDS"
        assert cmd not in _CMD_META, f"{cmd} still in _CMD_META"


def test_removed_modules_not_importable():
    with pytest.raises(ModuleNotFoundError):
        import bouzecode.cloudsave  # noqa: F401
    with pytest.raises(ModuleNotFoundError):
        import bouzecode.backend.commands.cloudsave_cmd  # noqa: F401
    with pytest.raises(ModuleNotFoundError):
        import bouzecode.backend.commands.voice_cmd  # noqa: F401
    with pytest.raises(ModuleNotFoundError):
        import bouzecode.backend.commands.video_cmd  # noqa: F401
    with pytest.raises(ModuleNotFoundError):
        import bouzecode.voice  # noqa: F401
    with pytest.raises(ModuleNotFoundError):
        import bouzecode.video  # noqa: F401


def test_cmd_exit_no_cloudsave_reference():
    import inspect
    from bouzecode.backend.commands.core.basic import cmd_exit

    source = inspect.getsource(cmd_exit)
    assert "cloudsave" not in source
    assert "upload_session" not in source
    assert "gist_token" not in source


def test_help_text_no_removed_commands():
    import bouzecode.ui.cli
    help_text = bouzecode.ui.cli.__doc__

    assert "/voice" not in help_text
    assert "/cloudsave" not in help_text
    assert "/video" not in help_text
