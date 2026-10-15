# [desc] Routes the "bouzecode" logger to a per-process file so backend warnings never print into the chat. [/desc]
"""File logging for the CLI / REPL entry point.

Nothing in the package configured ``logging``, so every ``logger.warning`` of a
backend module fell through to ``logging.lastResort`` and printed on stderr in
the middle of a turn. ``configure_cli_logging`` sends the whole ``bouzecode``
logger tree to a file instead and stops propagation.

One file per process, so no rotation ever renames a file another process holds
(on Windows that rename fails and logging prints "--- Logging error ---" on
stderr — the very pollution this module removes):

- web_v2 agent (``--web-agent-dir <ipc>``): ``<ipc>/backend.log``, append only,
  never rotated; it lives and is purged with the agent's ``.ipc`` folder.
- REPL / ``-p``: ``~/.bouzecode/logs/cli-<pid>.log``, rotated by this process
  only. ``purge_old_cli_logs`` removes those older than 7 days at startup.

Called only from ``ui.cli.main`` — never at import time, so tests relying on
``caplog`` keep the default propagation.
"""
import logging
import os
import re
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import psutil

LOGGER_NAME = "bouzecode"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3
MAX_AGE_DAYS = 7
LOG_FORMAT = "%(asctime)s %(levelname)s [%(process)d] %(name)s: %(message)s"
WEB_AGENT_LOG_NAME = "backend.log"
_CLI_LOG_PATTERN = re.compile(r"^cli-(\d+)\.log(\.\d+)?$")


def cli_log_path(logs_dir: Path, web_agent_dir: str = "") -> Path:
    """The log file owned by THIS process."""
    if web_agent_dir:
        return Path(web_agent_dir) / WEB_AGENT_LOG_NAME
    return Path(logs_dir) / f"cli-{os.getpid()}.log"


def purge_old_cli_logs(logs_dir: Path, max_age_days: float = MAX_AGE_DAYS) -> list[Path]:
    """Delete ``cli-<pid>.log*`` older than ``max_age_days`` whose pid is no longer alive."""
    logs_dir = Path(logs_dir)
    if not logs_dir.is_dir():
        return []
    cutoff = time.time() - max_age_days * 86400
    removed = []
    for path in logs_dir.glob("cli-*.log*"):
        match = _CLI_LOG_PATTERN.match(path.name)
        if not match or path.stat().st_mtime >= cutoff:
            continue
        if psutil.pid_exists(int(match.group(1))):
            continue  # a live process may still hold it
        path.unlink()
        removed.append(path)
    return removed


def configure_cli_logging(log_file: Path, rotate: bool = True) -> logging.Logger:
    """Attach one file handler to the ``bouzecode`` logger (idempotent)."""
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    target = str(log_file.resolve())
    if any(isinstance(h, logging.FileHandler) and h.baseFilename == target
           for h in logger.handlers):
        return logger
    if rotate:
        handler = RotatingFileHandler(target, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
                                      encoding="utf-8", delay=True)
    else:
        handler = logging.FileHandler(target, encoding="utf-8", delay=True)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    return logger


def current_log_file() -> Path | None:
    """Path of the file the ``bouzecode`` logger writes to, or None if not configured."""
    for handler in logging.getLogger(LOGGER_NAME).handlers:
        if isinstance(handler, logging.FileHandler):
            return Path(handler.baseFilename)
    return None


def setup_process_logging(logs_dir: Path, web_agent_dir: str = "") -> Path:
    """Entry-point wiring: purge stale CLI logs, then log to this process's own file."""
    log_file = cli_log_path(logs_dir, web_agent_dir)
    if not web_agent_dir:
        purge_old_cli_logs(logs_dir)
    configure_cli_logging(log_file, rotate=not web_agent_dir)
    return log_file
