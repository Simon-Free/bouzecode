# [desc] Regression: `-p --resume-deferred <err>` (no positional prompt) must reach repl, not exit. [/desc]
"""The web runner respawns a failed deferred check with `-p --resume-deferred <error>` and
NO positional prompt (the prompt is synthesized in repl from the error log). main() used to
reject that with `--print requires a prompt argument` and exit(1) — so the model never saw
the failure and the runner re-drained/re-respawned forever (146x loop, Azure deploy). This
guards that a deferred resume boots into repl, while a bare `-p` with no prompt still exits.

No unittest.mock — pytest.monkeypatch on argv + the repl entrypoint."""
from __future__ import annotations

import sys

import pytest

import bouzecode.ui.cli as cli


@pytest.fixture()
def stub_repl(monkeypatch, tmp_path):
    calls = {}
    # config.CONFIG_DIR & co sont figés à l'import sur le HOME du worker ; main() les crée
    # (load_config, logs). Le plugin pytest_home_etanche refuse ce mkdir : on les redirige.
    from bouzecode.backend.core import config
    data = tmp_path / "bouzecode_data"
    monkeypatch.setattr(config, "CONFIG_DIR", data)
    monkeypatch.setattr(config, "CONFIG_FILE", data / "config.json")
    monkeypatch.setattr(config, "HISTORY_FILE", data / "input_history.txt")
    monkeypatch.setattr(config, "SESSIONS_DIR", data / "sessions")
    monkeypatch.setattr(config, "LOGS_DIR", data / "logs")
    # main() does a local `from .repl import repl`, so patch the source module.
    monkeypatch.setattr("bouzecode.ui.repl.repl",
                        lambda config, initial_prompt=None: calls.setdefault("repl", initial_prompt))
    # Même raison : main() importe `has_api_key` localement depuis la config.
    monkeypatch.setattr("bouzecode.backend.core.config.has_api_key", lambda config: True)
    # main() installe ripgrep dans ~/.local/bin s'il manque : un test ne télécharge rien et
    # n'écrit jamais dans le vrai HOME.
    monkeypatch.setattr(cli, "_ensure_ripgrep", lambda *a, **k: None)
    return calls


def test_resume_deferred_without_prompt_reaches_repl(monkeypatch, stub_repl):
    monkeypatch.setattr(sys, "argv", ["bouzecode", "-p", "--resume-deferred", "boom: deploy failed"])
    cli.main()  # must NOT SystemExit
    assert "repl" in stub_repl, "deferred resume never reached repl (guard rejected it)"
    assert stub_repl["repl"] is None  # no positional prompt, as the runner spawns it


def test_print_without_prompt_still_exits(monkeypatch, stub_repl):
    monkeypatch.setattr(sys, "argv", ["bouzecode", "-p"])
    with pytest.raises(SystemExit):
        cli.main()
    assert "repl" not in stub_repl  # guard fired before repl
