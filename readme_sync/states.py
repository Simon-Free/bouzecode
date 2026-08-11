# [desc] Defines FolderState enum (FRESH/STALE/MISSING/ORPHAN) and FolderStatus dataclass for folder inspection results. [/desc]
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class FolderState(str, Enum):
    """Freshness of a code folder relative to its README + lock."""

    FRESH = "FRESH"      # README + lock coherent with code hashes
    STALE = "STALE"      # hash mismatch / new file / deleted file / lock flagged stale
    MISSING = "MISSING"  # code folder with no README
    ORPHAN = "ORPHAN"    # README present but no code files
    # Map present, no lock sidecar: the lock is a generated, git-ignored cache,
    # so a clean clone has none. Nothing PROVES the map drifted — reporting it
    # as STALE made `--check` fail on every documented folder of a fresh clone.
    UNLOCKED = "UNLOCKED"


@dataclass
class FolderStatus:
    """Result of inspecting one folder."""

    path: Path
    state: FolderState
    reasons: list[str] = field(default_factory=list)

    @property
    def needs_attention(self) -> bool:
        return self.state in (FolderState.MISSING, FolderState.STALE)
