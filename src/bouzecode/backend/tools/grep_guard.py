# [desc] Grep/Glob guard — formerly blocked root searches, now a no-op (gitignore handles filtering). [/desc]
"""Grep/Glob guard — DISABLED.

Root-search blocking has been replaced by automatic .gitignore respect
in ripgrep (--no-require-git). The install_grep_guard() function is kept
as a no-op to avoid import errors from registration.py.
"""
from __future__ import annotations


def install_grep_guard() -> None:
    """No-op. Gitignore-based filtering in _grep/_glob replaces root blocking."""
    pass
