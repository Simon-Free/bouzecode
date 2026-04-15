#!/usr/bin/env python3
# [desc] Setup script to detect and install optional ripgrep dependency across platforms. [/desc]
"""Setup script for optional bouzecode dependencies (ripgrep, etc.)."""
import platform
import shutil
import subprocess
import sys


def _run(cmd: list[str]) -> bool:
    try:
        subprocess.run(cmd, check=True, timeout=120)
        return True
    except Exception as e:
        print(f"  Failed: {e}")
        return False


def setup_ripgrep(auto: bool = False) -> None:
    if shutil.which("rg"):
        print("ripgrep (rg) is already installed.")
        return

    print("ripgrep (rg) is not installed.")
    print("It speeds up the Grep tool 5-10x compared to plain grep.")
    if not auto:
        answer = input("Install it now? [Y/n] ").strip().lower()
        if answer and answer != "y":
            print("Skipped.")
            return

    os_name = platform.system()
    installed = False

    if os_name == "Windows":
        print("Trying: winget install BurntSushi.ripgrep.MSVC ...")
        installed = _run(["winget", "install", "BurntSushi.ripgrep.MSVC",
                          "--accept-source-agreements", "--accept-package-agreements"])
    elif os_name == "Darwin":
        print("Trying: brew install ripgrep ...")
        installed = _run(["brew", "install", "ripgrep"])
    elif os_name == "Linux":
        if shutil.which("apt"):
            print("Trying: sudo apt install ripgrep ...")
            installed = _run(["sudo", "apt", "install", "-y", "ripgrep"])
        elif shutil.which("cargo"):
            print("Trying: cargo install ripgrep ...")
            installed = _run(["cargo", "install", "ripgrep"])

    if not installed:
        print("Auto-install failed. Install manually:")
        print("  https://github.com/BurntSushi/ripgrep#installation")
        return

    if shutil.which("rg"):
        v = subprocess.check_output(["rg", "--version"], text=True).strip()
        print(f"Installed successfully: {v}")
    else:
        print("Installed, but 'rg' not yet in PATH. Restart your terminal.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Setup optional bouzecode dependencies")
    parser.add_argument("--auto-install-ripgrep", action="store_true",
                        help="Install ripgrep without asking")
    args = parser.parse_args()
    setup_ripgrep(auto=args.auto_install_ripgrep)
