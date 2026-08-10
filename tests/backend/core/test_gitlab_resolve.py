# [desc] Tests de résolution (URL + dossier git local → repo plugin online) et dérivation (nom pip + source git). Pas de réseau : on ne clone pas, on ne pip-install pas. [/desc]
"""resolve_input turns a browser URL or a local git folder into online coords;
plugin_install_target derives the pip name + git+https source for the installer.

No network here: cloning / pip-install happen only in production (and fail loud if
the repo isn't reachable). We test the resolution layer, which reads git locally.
"""
from __future__ import annotations

import subprocess

import pytest

from bouzecode.backend.core.gitlab_resolve import (
    SourceError, _parse_gitlab_url, plugin_install_target, resolve_input,
)


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def test_parse_plain_repo_url():
    scheme, host, project, ref, subpath = _parse_gitlab_url("https://h.example.com/grp/sub/repo")
    assert (scheme, host, project) == ("https", "h.example.com", "grp/sub/repo")
    assert ref is None and subpath is None


def test_parse_tree_url_carries_ref_and_subpath():
    _, _, project, ref, subpath = _parse_gitlab_url(
        "https://h.example.com/grp/sub/repo/-/tree/develop/sub"
    )
    assert project == "grp/sub/repo" and ref == "develop" and subpath == "sub"


def test_parse_strips_dot_git_suffix():
    _, _, project, _, _ = _parse_gitlab_url("https://h.example.com/grp/sub/repo.git")
    assert project == "grp/sub/repo"


def test_ssh_remote_normalized_to_https():
    info = resolve_input("git@h.example.com:grp/my-plugin.git")
    assert info["web_url"] == "https://h.example.com/grp/my-plugin"


def test_plugin_install_target_derives_name_and_git_source():
    info = resolve_input("https://h.example.com/voy/myorg/my-plugin")
    package, git_source = plugin_install_target(info)
    assert package == "my-plugin"
    assert git_source == "git+https://h.example.com/voy/myorg/my-plugin.git"


def test_invalid_input_is_rejected():
    with pytest.raises(SourceError):
        resolve_input("not-a-url-not-a-dir")


def test_local_path_deduces_remote(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "remote", "add", "origin", "git@h.example.com:grp/my-plugin.git")

    info = resolve_input(str(tmp_path))
    package, git_source = plugin_install_target(info)

    assert info["web_url"] == "https://h.example.com/grp/my-plugin"
    assert package == "my-plugin"
    assert git_source == "git+https://h.example.com/grp/my-plugin.git"


def test_local_path_without_remote_errors(tmp_path):
    _git(tmp_path, "init")
    with pytest.raises(SourceError):
        resolve_input(str(tmp_path))
