# [desc] Detects Windows Terminal or cmd and spawns sub-agent bouzecode processes in new terminal tabs. [/desc]
"""Spawn sub-agents in a new terminal window/tab on Windows.

Used when bouzecode runs interactively in a terminal (not bouzeui).
The sub-agent gets its own terminal so the user can watch in real-time.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

_log = logging.getLogger(__name__)


def detect_terminal_app() -> str:
    """Return 'wt' if Windows Terminal is available, else 'cmd'."""
    if shutil.which("wt.exe") or shutil.which("wt"):
        return "wt"
    return "cmd"


def prompt_file_path(result_file: str) -> str:
    """Fichier du brief de l'enfant, à côté de son fichier résultat (`<stem>.prompt.txt`)."""
    return str(Path(result_file).with_suffix(".prompt.txt"))


def _titre_sur(prompt: str) -> str:
    """40 premiers caractères du brief, sans ce que `wt.exe` interprète (`;`, guillemets)."""
    debut = " ".join(prompt[:40].split())
    return "".join(c for c in debut if c not in ';"')


def build_terminal_command(
    prompt: str,
    result_file: str,
    config: dict,
    terminal_app: str | None = None,
) -> list[str]:
    """Build the command list to spawn bouzecode in a new terminal.

    Pure function — does not launch anything.
    """
    if terminal_app is None:
        terminal_app = detect_terminal_app()

    python = sys.executable
    title = f"Agent: {_titre_sur(prompt)}"

    #  Le brief ne passe JAMAIS en argument : `wt.exe` lit `;` comme un séparateur de
    #  sous-commandes et coupe la ligne au premier — le 2026-10-06, deux enfants ont reçu
    #  57 % et 15 % de leur brief, SANS `--result-file` ni `--accept-all` (placés après), et
    #  sont restés bloqués sur une question. Il voyage dans un fichier ; les options d'abord.
    bouzecode_args = [
        python, "-m", "bouzecode",
        "--result-file", result_file,
        "--accept-all",
    ]

    model = config.get("model")
    if model:
        bouzecode_args.extend(["--model", model])
    bouzecode_args.extend(["-p", "--prompt-file", prompt_file_path(result_file)])

    if terminal_app == "wt":
        # `-w -1` forces a brand new Windows Terminal WINDOW (not just a tab
        # in an existing window) — the task requires a separate command window.
        return [
            "wt.exe", "-w", "-1", "new-tab",
            "--title", title,
            "--",
            *bouzecode_args,
        ]
    else:
        # cmd /c start "title" cmd /<flag> <command>
        # Default to /c so the window auto-closes once the sub-agent finishes
        # (avoids orphan windows piling up). Use /k only when the opt-in debug
        # flag config["_terminal_keep_open"] is set (interactive inspection).
        inner_flag = "/k" if config.get("_terminal_keep_open") else "/c"
        inner = " ".join(f'"{a}"' if " " in a else a for a in bouzecode_args)
        return ["cmd", "/c", "start", f'"{title}"', "cmd", inner_flag, inner]


def _spawn_via_cmd(prompt: str, result_file: str, config: dict,
                   env: dict | None = None) -> subprocess.Popen:
    """The `cmd /c start` path. Needs shell=True on Windows."""
    cmd = build_terminal_command(prompt, result_file, config, terminal_app="cmd")
    return subprocess.Popen(" ".join(cmd), shell=True, env=env)


def spawn_in_terminal(
    prompt: str,
    result_file: str,
    config: dict,
    env_extra: dict | None = None,
) -> subprocess.Popen:
    """Launch bouzecode in a new terminal window. Returns the Popen handle.

    `env_extra` (ex. `BOUZECODE_AGENT_DEPTH`) s'ajoute à l'environnement hérité.

    ``wt.exe`` is not a real executable: it is an App Execution Alias, a zero-byte
    reparse point under ``%LOCALAPPDATA%\\Microsoft\\WindowsApps``. ``shutil.which``
    finds it because it walks PATH and sees a file, but ``CreateProcess`` resolves
    the alias through the package registration, which is not available from every
    process context. From a headless agent spawned by web_v2 it fails with
    ``[WinError 2] Le fichier spécifié est introuvable`` (0x80070002) — measured on
    2026-08-22, where it killed every sub-agent spawn while ``wt.exe`` launched
    perfectly from an interactive shell.

    Detection therefore cannot be trusted on its own: we try, and fall back to the
    ``cmd`` path, which is a real executable and always launchable.
    """
    env = {**os.environ, **env_extra} if env_extra else None
    Path(prompt_file_path(result_file)).write_text(prompt, encoding="utf-8")
    if detect_terminal_app() == "wt":
        try:
            cmd = build_terminal_command(prompt, result_file, config, terminal_app="wt")
            return subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                                    env=env)
        except OSError as exc:
            _log.warning(
                "wt.exe annonce par PATH mais non lancable (%s) - repli sur cmd", exc,
            )
    return _spawn_via_cmd(prompt, result_file, config, env)
