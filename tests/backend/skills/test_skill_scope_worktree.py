# [desc] A scope written as an absolute path to the main checkout still applies inside a linked git worktree; a genuine tie is refused, not guessed. [/desc]
"""Scope inside a linked git worktree — the edge case that would pass unnoticed.

The project runs one worktree per ticket, so an agent's cwd is `…/proj_wt1`, not `…/proj`.
A skill whose `scope:` was written as an absolute path to the main checkout must keep
applying there, otherwise every explicitly scoped skill would vanish in the very mode the
project runs in.

Because a worktree adds a second anchor, it is also the one situation where two skills can
genuinely tie: same name, same store, scopes of equal depth. The resolver refuses to pick
one at random and says so.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
CLOSE = "C'est fait."

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")


def _git(repo, *args) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _write_skill(store, folder: str, frontmatter: str, body: str) -> None:
    target = store / folder
    target.mkdir(parents=True, exist_ok=True)
    (target / "skill.md").write_text(f"---\n{frontmatter}---\n\n{body}\n", encoding="utf-8")


@pytest.fixture()
def linked_worktree(tmp_path):
    """A real repo plus a linked worktree of it, the way a ticket runs."""
    main = tmp_path / "proj"
    main.mkdir()
    _git(main, "init", "-q")
    _git(main, "config", "user.email", "t@t.t")
    _git(main, "config", "user.name", "t")
    (main / "seed.txt").write_text("seed", encoding="utf-8")
    _git(main, "add", "-A")
    _git(main, "commit", "-qm", "seed")
    worktree = tmp_path / "proj_wt1"
    _git(main, "worktree", "add", "-q", str(worktree), "-b", "ticket")
    return main, worktree


def _skill_result(cwd, monkeypatch, name: str) -> str:
    monkeypatch.chdir(cwd)
    call = f'<tool_use name="Skill" id="sk1"><param name="name">{name}</param></tool_use>'
    result = bouzecode([f"use {name}"], mock_llm=MockLLM([f"{METH}\n{call}", CLOSE]))
    return next(m["content"] for m in result.messages
                if m.get("role") == "tool" and m.get("name") == "Skill")


def test_a_scope_pointing_at_the_main_checkout_applies_inside_the_worktree(
        linked_worktree, monkeypatch):
    """An absolute `scope:` on the main repo is honoured from a linked worktree."""
    main, worktree = linked_worktree
    _write_skill(worktree / ".bouzecode" / "skills", "release",
                 f"name: release\ndescription: release steps\nscope: {main.as_posix()}\n",
                 "Release from the MAIN checkout.")

    assert "Release from the MAIN checkout" in _skill_result(worktree, monkeypatch, "release")


def test_a_scope_pointing_at_an_unrelated_repo_still_does_not_apply(
        linked_worktree, tmp_path, monkeypatch):
    """The worktree anchor widens the scope to its own repo only — not to anything else."""
    _, worktree = linked_worktree
    stranger = tmp_path / "stranger"
    stranger.mkdir()
    _write_skill(worktree / ".bouzecode" / "skills", "foreign",
                 f"name: foreign\ndescription: foreign\nscope: {stranger.as_posix()}\n",
                 "Should never be served.")

    assert "not found" in _skill_result(worktree, monkeypatch, "foreign")


def test_two_equally_specific_scopes_are_refused_rather_than_guessed(
        linked_worktree, monkeypatch):
    """Same name, same store, scopes of equal depth: the model is told to qualify."""
    main, worktree = linked_worktree
    store = worktree / ".bouzecode" / "skills"
    _write_skill(store, "dual-worktree", "name: dual\ndescription: worktree flavour\n",
                 "Worktree flavour.")
    _write_skill(store, "dual-main",
                 f"name: dual\ndescription: main flavour\nscope: {main.as_posix()}\n",
                 "Main flavour.")

    out = _skill_result(worktree, monkeypatch, "dual")
    assert "ambiguous" in out
    assert "proj:dual" in out
    assert "proj_wt1:dual" in out
