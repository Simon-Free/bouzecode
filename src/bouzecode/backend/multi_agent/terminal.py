# [desc] Detects Windows Terminal or cmd and spawns sub-agent bouzecode processes in new terminal tabs. [/desc]
"""Spawn sub-agents in a new terminal window/tab on Windows.

Used when bouzecode runs interactively in a terminal (not BouzéqUI).
The sub-agent gets its own terminal so the user can watch in real-time.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def detect_terminal_app() -> str:
    """Return 'wt' if Windows Terminal is available, else 'cmd'."""
    if shutil.which("wt.exe") or shutil.which("wt"):
        return "wt"
    return "cmd"


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
    title = f"Agent: {prompt[:40]}"

    bouzecode_args = [
        python, "-m", "bouzecode",
        "-p", prompt,
        "--result-file", result_file,
        "--accept-all",
    ]

    model = config.get("model")
    if model:
        bouzecode_args.extend(["--model", model])

    if terminal_app == "wt":
        return [
            "wt.exe", "new-tab",
            "--title", title,
            "--",
            *bouzecode_args,
        ]
    else:
        # cmd /c start "title" cmd /k <command>
        # Using /k so the window stays open after completion
        inner = " ".join(f'"{a}"' if " " in a else a for a in bouzecode_args)
        return ["cmd", "/c", "start", f'"{title}"', "cmd", "/k", inner]


def spawn_in_terminal(
    prompt: str,
    result_file: str,
    config: dict,
) -> subprocess.Popen:
    """Launch bouzecode in a new terminal window. Returns the Popen handle."""
    cmd = build_terminal_command(prompt, result_file, config)
    terminal_app = detect_terminal_app()

    if terminal_app == "wt":
        return subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        # For cmd /c start, we need shell=True on Windows
        return subprocess.Popen(" ".join(cmd), shell=True)
