from __future__ import annotations

import os
from pathlib import Path

# Kept as the single opt-out, as it has always been: the variable already exists
# in deployed environments and renaming it would silently re-enable the feature
# where someone had turned it off. BOUZECODE_AGENTS_MAP is honoured too.
_DISABLED_VALUES = {"0", "false", "off", "no"}
_CODE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css"}


def _env_enabled() -> bool:
    return os.environ.get("BOUZECODE_README_SYNC", "").strip().lower() not in _DISABLED_VALUES


def mark_readme_stale(file_path: str) -> None:
    """Record that THIS agent just wrote code in a folder.

    Push (this hook) and pull (the frontmatter hash, read by
    `tools.agents_map.serve`) are not redundant and neither supersedes the other,
    because they answer different questions:

    * The HASH answers "is the map out of date?" and is the source of truth. It
      is the only one that sees a `git pull`, another worktree, or a human in an
      IDE — changes a write hook is structurally blind to. That blindness is
      measured: 0 of 43 `.agents.lock` ever carried `stale:true` while 5 folders
      really had diverged.
    * This HOOK answers "did the current agent cause the divergence?", which the
      hash cannot know. An agent refactoring a folder invalidates its own map on
      every `Write`; regenerating there would bill it repeatedly for churn it is
      still producing. So a self-authored folder is served stale-with-a-marker
      and left for the next agent that READS it.

    So the hook survives, demoted from "flag staleness" (which nothing consumed)
    to "attribute authorship" (which `serve` consumes). NEVER raises: attributing
    a write must not break a turn.
    """
    if not file_path or not _env_enabled():
        return
    path = Path(file_path)
    if path.suffix not in _CODE_SUFFIXES:
        return
    from ..tools.agents_map import feature_enabled
    from ..tools.agents_map.serve import mark_self_authored

    if feature_enabled():
        mark_self_authored(path.parent)
