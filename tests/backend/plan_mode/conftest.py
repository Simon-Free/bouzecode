# [desc] Runs every plan-mode test from a scratch cwd so plan files never land in this checkout. [/desc]
"""Plan mode persists `<cwd>/.nano_claude/plans/<session>.md`.

Run from the repository root — which is what pytest does — that path is a
git-tracked file, so the suite left `git status` dirty after every run. Every
test in this folder therefore gets a throwaway cwd.
"""
import pytest


@pytest.fixture(autouse=True)
def _plan_files_stay_out_of_the_repo(agent_cwd):
    """`agent_cwd` (tests/conftest.py) chdirs into tmp_path for the whole test."""
