from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .naming import LOCK_VERSION, doc_name, lock_name
from .states import FolderState, FolderStatus

IGNORE_DIRS = {
    ".venv", ".venv-ui", "venv", "env", "node_modules", "dist", "build",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", "htmlcov",
    "deploy_build", "bin", ".git", "__pycache__", ".idea", ".vscode",
    "vendor",
}
# A folder map documents hand-written source, whatever the language. `vendor`
# sits in IGNORE_DIRS for the same reason as `node_modules`: third-party code
# shipped in-tree is not ours to document.
CODE_EXTS = {".py", ".js"}


def sha256_file(path: Path) -> str:
    """Hex sha256 of a file's bytes."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def count_lines(path: Path) -> int:
    """Number of lines in a text file (bytes-safe)."""
    return path.read_bytes().count(b"\n") + 1


def is_ignored_dir(name: str, path: Path | None = None) -> bool:
    """A dir we never document: junk/cache by name, an *.egg-info, or any
    virtualenv (a `pyvenv.cfg` marks one whatever it is named)."""
    if name in IGNORE_DIRS or name.endswith(".egg-info"):
        return True
    if path is not None and (path / "pyvenv.cfg").exists():
        return True
    return False


def git_ignored_paths(root: Path) -> set[Path]:
    """Resolved directories git ignores under root (collapsed to the top dir).

    Empty when root is not a git repo or git is unavailable — the walk then
    relies on IGNORE_DIRS and the pyvenv.cfg probe alone."""
    import shutil
    import subprocess

    if shutil.which("git") is None:
        return set()
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--others", "--ignored",
         "--exclude-standard", "--directory"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return set()
    ignored: set[Path] = set()
    for line in result.stdout.splitlines():
        entry = line.strip().rstrip("/")
        if entry:
            ignored.add((root / entry).resolve())
    return ignored


def is_code_file(path: Path) -> bool:
    return path.suffix in CODE_EXTS


def code_files(folder: Path) -> list[Path]:
    """Direct code files in a folder (non-recursive), sorted by name."""
    out = [
        p for p in folder.iterdir()
        if p.is_file() and is_code_file(p)
    ]
    return sorted(out, key=lambda p: p.name)


def iter_code_folders(root: Path):
    """Yield every folder under root (incl. root) that is not inside an ignored dir."""
    root = root.resolve()
    ignored = git_ignored_paths(root)
    stack = [root]
    while stack:
        folder = stack.pop()
        yield folder
        for child in sorted(folder.iterdir(), key=lambda p: p.name):
            if not child.is_dir():
                continue
            if is_ignored_dir(child.name, child):
                continue
            if child.resolve() in ignored:
                continue
            stack.append(child)


def compute_manifest(folder: Path) -> dict:
    """Build the {name: {sha256, lines}} map for a folder's code files."""
    files: dict[str, dict] = {}
    for p in code_files(folder):
        files[p.name] = {"sha256": sha256_file(p), "lines": count_lines(p)}
    return files


def lock_path(folder: Path) -> Path:
    return folder / lock_name()


def read_lock(folder: Path) -> dict | None:
    lp = lock_path(folder)
    if not lp.exists():
        return None
    return json.loads(lp.read_text(encoding="utf-8"))


def write_lock(folder: Path, stale: bool = False) -> dict:
    """Recompute the manifest and write the lock sidecar. Returns the lock dict."""
    lock = {
        "version": LOCK_VERSION,
        "doc": doc_name(),
        "files": compute_manifest(folder),
        "stale": stale,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    lock_path(folder).write_text(
        json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return lock


def set_lock_stale(folder: Path, stale: bool = True) -> dict:
    """Flip the stale flag on an existing lock, or create one if missing."""
    lock = read_lock(folder)
    if lock is None:
        lock = {
            "version": LOCK_VERSION,
            "doc": doc_name(),
            "files": compute_manifest(folder),
            "stale": stale,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    else:
        lock["stale"] = stale
    lock_path(folder).write_text(
        json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return lock


def _manifest_diff(folder: Path, lock: dict) -> list[str]:
    """Reasons the folder's code diverges from its lock manifest (empty = fresh)."""
    reasons: list[str] = []
    current = compute_manifest(folder)
    recorded = lock.get("files", {})
    cur_names, rec_names = set(current), set(recorded)
    for name in sorted(cur_names - rec_names):
        reasons.append(f"new file: {name}")
    for name in sorted(rec_names - cur_names):
        reasons.append(f"deleted file: {name}")
    for name in sorted(cur_names & rec_names):
        if current[name]["sha256"] != recorded[name].get("sha256"):
            reasons.append(f"hash changed: {name}")
    return reasons


def classify(folder: Path) -> FolderStatus:
    """Determine the FolderState of a single folder."""
    has_code = bool(code_files(folder))
    has_doc = (folder / doc_name()).exists()

    if has_code and not has_doc:
        return FolderStatus(folder, FolderState.MISSING, [f"no {doc_name()}"])
    if not has_code and has_doc:
        return FolderStatus(folder, FolderState.ORPHAN, [f"{doc_name()} with no code"])
    if not has_code and not has_doc:
        return FolderStatus(folder, FolderState.FRESH, [])

    lock = read_lock(folder)
    if lock is None:
        return FolderStatus(
            folder, FolderState.UNLOCKED,
            [f"no {lock_name()} yet — drift cannot be checked"],
        )
    reasons = _manifest_diff(folder, lock)
    if lock.get("stale"):
        reasons.insert(0, "lock flagged stale")
    if reasons:
        return FolderStatus(folder, FolderState.STALE, reasons)
    return FolderStatus(folder, FolderState.FRESH, [])


def scan(root: Path) -> list[FolderStatus]:
    """Classify every non-ignored folder under root. FRESH-empty folders omitted."""
    out: list[FolderStatus] = []
    for folder in iter_code_folders(root):
        status = classify(folder)
        has_code = bool(code_files(folder))
        has_doc = (folder / doc_name()).exists()
        if status.state == FolderState.FRESH and not has_code and not has_doc:
            continue
        out.append(status)
    return out
