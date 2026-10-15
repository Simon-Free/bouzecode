# [desc] Tests that bouzecode installs the ripgrep build matching the OS/arch, verifies it, and falls back silently to grep. [/desc]
"""_ensure_ripgrep téléchargeait rg.exe (Windows) même sous Linux : l'outil Grep
retombait alors sur grep. Ces tests n'utilisent pas le réseau : le téléchargement
est une couture injectée qui copie une archive fabriquée dans tmp_path."""
from __future__ import annotations

import io
import os
import platform
import shutil
import sys
import tarfile
import urllib.error
import zipfile
from pathlib import Path

import pytest

from bouzecode.ui import cli
from bouzecode.ui.cli import _ensure_ripgrep, _install_ripgrep, _rg_asset

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="faux rg en script shell")

GOOD_RG = b"#!/bin/sh\necho 'ripgrep 14.1.1'\n"
BAD_RG = b"#!/bin/sh\nexit 1\n"


@pytest.mark.parametrize("system, machine, expected", [
    ("Linux", "x86_64", "ripgrep-14.1.1-x86_64-unknown-linux-musl.tar.gz"),
    ("Linux", "aarch64", "ripgrep-14.1.1-aarch64-unknown-linux-gnu.tar.gz"),
    ("Darwin", "arm64", "ripgrep-14.1.1-aarch64-apple-darwin.tar.gz"),
    ("Darwin", "x86_64", "ripgrep-14.1.1-x86_64-apple-darwin.tar.gz"),
    ("Windows", "AMD64", "ripgrep-14.1.1-x86_64-pc-windows-msvc.zip"),
    ("Linux", "s390x", None),
])
def test_asset_matches_platform_and_arch(system, machine, expected):
    assert _rg_asset(system, machine) == expected


def _make_archive(path: Path, member: str, payload: bytes) -> Path:
    if path.name.endswith(".zip"):
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(member, payload)
    else:
        with tarfile.open(path, "w:gz") as tf:
            info = tarfile.TarInfo(member)
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
    return path


def _serving(archive: Path, calls: list):
    """Couture de téléchargement : copie `archive` au lieu d'aller sur GitHub."""
    def download(url, dest):
        calls.append(url)
        shutil.copyfile(archive, dest)
    return download


@posix_only
@pytest.mark.parametrize("suffix", [".tar.gz", ".zip"])
def test_install_extracts_executable_verified_rg(tmp_path, monkeypatch, suffix):
    archive = _make_archive(tmp_path / f"fake{suffix}", "ripgrep-14.1.1/rg", GOOD_RG)
    asset = "fake-asset" + suffix
    monkeypatch.setattr(cli, "_rg_asset", lambda system, machine: asset)
    calls: list = []
    install_dir = tmp_path / "home" / ".local" / "bin"

    target = _install_ripgrep(install_dir, "Linux", "x86_64", _serving(archive, calls))

    assert target == install_dir / "rg"
    assert os.access(target, os.X_OK)
    assert cli._rg_works(str(target))
    assert calls and calls[0].endswith("/14.1.1/" + asset)


@posix_only
def test_binary_failing_version_is_not_kept(tmp_path):
    archive = _make_archive(tmp_path / "bad.tar.gz", "ripgrep-14.1.1/rg", BAD_RG)
    install_dir = tmp_path / "bin"

    target = _install_ripgrep(install_dir, "Linux", "x86_64", _serving(archive, []))

    assert target is None
    assert not (install_dir / "rg").exists()


@posix_only
def test_ensure_installs_under_home_and_puts_it_on_path(tmp_path, monkeypatch):
    archive = _make_archive(tmp_path / "rg.tar.gz", "ripgrep-14.1.1/rg", GOOD_RG)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("BOUZECODE_RIPGREP_AUTO", raising=False)
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")

    _ensure_ripgrep(download=_serving(archive, []))

    install_dir = tmp_path / "home" / ".local" / "bin"
    assert (install_dir / "rg").is_file()
    assert os.environ["PATH"].split(os.pathsep)[0] == str(install_dir)
    assert shutil.which("rg") == str(install_dir / "rg")


def test_download_error_falls_back_with_a_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("BOUZECODE_RIPGREP_AUTO", raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", "/nonexistent")

    def offline(url, dest):
        raise urllib.error.URLError("hors ligne")

    _ensure_ripgrep(download=offline)  # ne doit pas lever

    assert os.environ["PATH"] == "/nonexistent"
    out = capsys.readouterr()
    assert out.out == ""
    assert "ripgrep" in out.err and "pip install ripgrep" in out.err
