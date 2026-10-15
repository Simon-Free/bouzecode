# [desc] The CLI routes backend loggers to a per-process file, never to the console. [/desc]
"""cli_logging: backend warnings land in this process's own log file, not on stderr."""
import logging
import os
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler

from bouzecode.ui.ansi import warn
from bouzecode.ui.cli_logging import (
    configure_cli_logging, current_log_file, purge_old_cli_logs, setup_process_logging,
)

EIGHT_DAYS = 8 * 86400


def _flush():
    for handler in logging.getLogger("bouzecode").handlers:
        handler.flush()


def _age(path, seconds):
    old = time.time() - seconds
    os.utime(path, (old, old))


def _dead_pid():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_backend_warning_goes_to_file_not_console(tmp_path, capsys):
    log_file = setup_process_logging(tmp_path / "logs")
    assert log_file.name == f"cli-{os.getpid()}.log"

    logging.getLogger("bouzecode.backend.core.tls").warning("certificat refuse par le proxy")
    _flush()

    captured = capsys.readouterr()
    assert "certificat refuse" not in captured.err + captured.out
    content = log_file.read_text(encoding="utf-8")
    assert "WARNING" in content
    assert "bouzecode.backend.core.tls: certificat refuse par le proxy" in content
    assert current_log_file() == log_file.resolve()


def test_web_agent_logs_next_to_its_ipc_without_rotation(tmp_path):
    ipc_dir = tmp_path / "abc123.ipc"
    log_file = setup_process_logging(tmp_path / "logs", web_agent_dir=str(ipc_dir))

    assert log_file == ipc_dir / "backend.log"
    handlers = logging.getLogger("bouzecode").handlers
    assert not any(isinstance(h, RotatingFileHandler) for h in handlers)
    logging.getLogger("bouzecode.backend.x").error("boom")
    _flush()
    assert "boom" in log_file.read_text(encoding="utf-8")


def test_second_call_adds_no_handler(tmp_path):
    log_file = tmp_path / "logs" / "cli-1.log"
    logger = configure_cli_logging(log_file)
    count = len(logger.handlers)
    configure_cli_logging(log_file)
    assert len(logger.handlers) == count
    assert sum(isinstance(h, RotatingFileHandler) for h in logger.handlers) == 1
    assert logger.propagate is False


def test_purge_removes_only_old_logs_of_dead_processes(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    dead = _dead_pid()
    old_dead = logs / f"cli-{dead}.log"
    old_dead_rotated = logs / f"cli-{dead}.log.2"
    old_alive = logs / f"cli-{os.getpid()}.log"
    recent_dead = logs / f"cli-{dead}9.log"
    unrelated = logs / "notes.log"
    for path in (old_dead, old_dead_rotated, old_alive, recent_dead, unrelated):
        path.write_text("x", encoding="utf-8")
    for path in (old_dead, old_dead_rotated, old_alive, unrelated):
        _age(path, EIGHT_DAYS)

    removed = purge_old_cli_logs(logs)

    assert sorted(removed) == sorted([old_dead, old_dead_rotated])
    assert not old_dead.exists() and not old_dead_rotated.exists()
    assert old_alive.exists() and recent_dead.exists() and unrelated.exists()


def test_user_warnings_stay_visible(tmp_path, capsys):
    setup_process_logging(tmp_path / "logs")
    warn("message pour l'utilisateur")
    assert "message pour l'utilisateur" in capsys.readouterr().out
