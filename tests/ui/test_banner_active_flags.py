"""Ligne « Active: » de la bannière du REPL : pas de « None », niveau de thinking réel."""
import re

import pytest

from bouzecode.ui.repl import print_active_flags

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _banner_line(capsys, config: dict) -> str:
    print_active_flags(config)
    return _ANSI.sub("", capsys.readouterr().out)


@pytest.fixture(autouse=True)
def _no_thinking_env(monkeypatch):
    monkeypatch.delenv("BOUZECODE_THINKING", raising=False)


def test_banner_shows_resolved_thinking_level_without_none(capsys):
    config = {"thinking": True, "thinking_mode": "extended", "thinking_level": "high",
              "verbose": True}
    out = _banner_line(capsys, config)
    assert out == "Active: verbose · thinking:high\n"
    assert "None" not in out


def test_banner_defaults_to_medium_when_no_level_set(capsys):
    assert _banner_line(capsys, {"thinking": True}) == "Active: thinking:medium\n"


def test_banner_hides_thinking_when_level_is_none(capsys):
    assert _banner_line(capsys, {"thinking_level": "none", "verbose": True}) == "Active: verbose\n"
    assert _banner_line(capsys, {"thinking_mode": "off"}) == ""
