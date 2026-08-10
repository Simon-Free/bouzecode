"""readme_sync — hash-driven README synchronization for code folders.

A dev-facing tool (not shipped in the bouzecode wheel) that walks a repo, detects
which folder AGENTS.md docs are out of date via a per-folder ``.agents.lock``
sidecar, and regenerates them with a single custom LLM call.
"""

from .states import FolderState, FolderStatus

__all__ = ["FolderState", "FolderStatus"]
