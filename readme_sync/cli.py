from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .hashing import DOC_NAME, LOCK_NAME, LOCK_VERSION, scan
from .propagate import create_root_map
from .regen import regen_folder
from .states import FolderState

_OLD_LOCK_NAME = ".readme.lock"
_OLD_DOC_NAME = "README.md"


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)) or "."
    except ValueError:
        return str(path)


def cmd_check(root: Path) -> int:
    statuses = scan(root)
    flagged = [s for s in statuses if s.needs_attention]
    missing = [s for s in flagged if s.state == FolderState.MISSING]
    stale = [s for s in flagged if s.state == FolderState.STALE]
    orphan = [s for s in statuses if s.state == FolderState.ORPHAN]

    print(f"readme_sync --check  root={root}")
    # The scanned count is printed explicitly: it is the only honest measure of coverage.
    # Callers used to infer it from whatever number happened to be largest in this output,
    # which silently became wrong as soon as the repo was in sync (nothing left to list).
    print(f"  {len(statuses)} folders scanned")
    print(f"  {len(missing)} missing / {len(stale)} stale / {len(orphan)} orphan")
    for s in statuses:
        if s.state == FolderState.FRESH:
            continue
        rel = _rel(s.path, root)
        reason = "; ".join(s.reasons)
        print(f"  [{s.state.value}] {rel}  ({reason})")
    return 1 if flagged else 0


def cmd_list_stale(root: Path) -> int:
    statuses = scan(root)
    flagged = [s for s in statuses if s.needs_attention]
    for s in flagged:
        print(_rel(s.path, root))
    return 1 if flagged else 0


def cmd_regen(root: Path, path: str | None) -> int:
    if path is not None:
        target = Path(path)
        folder = target if target.is_absolute() else (root / target)
        regen_folder(folder.resolve(), root)
        print(f"regenerated {_rel(folder.resolve(), root)}")
        return 0

    statuses = scan(root)
    flagged = [s for s in statuses if s.needs_attention]
    for s in flagged:
        regen_folder(s.path, root)
        print(f"regenerated {_rel(s.path, root)}")
    return 0


def cmd_init(root: Path) -> int:
    statuses = scan(root)
    flagged = [s for s in statuses if s.needs_attention]
    print(f"readme_sync --init  root={root}")
    print(f"  {len(flagged)} folders to (re)generate")
    for s in flagged:
        regen_folder(s.path, root)
        print(f"regenerated {_rel(s.path, root)}")
    create_root_map(root)
    print(f"root map written: {_rel(root / DOC_NAME, root)}")
    return 0


def _is_git_tracked(path: Path, root: Path) -> bool:
    """True if the file is tracked by git at root. Untracked/errors => False."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path)],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return result.returncode == 0


def _migrate_lock_file(old_lock: Path) -> None:
    """Rename an old .readme.lock to .agents.lock, rewriting its doc field."""
    new_lock = old_lock.with_name(LOCK_NAME)
    try:
        data = json.loads(old_lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {"version": LOCK_VERSION}
    data.pop("readme", None)
    data["doc"] = DOC_NAME
    new_lock.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    old_lock.unlink()


def cmd_migrate(root: Path) -> int:
    """Migrate this morning's generated README.md leftovers to AGENTS.md.

    For every folder carrying an old `.readme.lock`:
    - if the adjacent README.md is NOT git-tracked (a generated doc) => rename
      README.md -> AGENTS.md and .readme.lock -> .agents.lock (doc field rewritten);
    - if README.md IS git-tracked (a human doc restored by hand) => leave the
      README alone, just delete the orphan .readme.lock;
    - if there is no README.md at all => just rename the lock to .agents.lock.
    Then regenerate the root map into AGENTS.md. Nothing else is touched.
    """
    root = root.resolve()
    renamed = 0
    lock_only = 0
    orphan_locks = 0
    print(f"readme_sync --migrate  root={root}")
    for old_lock in sorted(root.rglob(_OLD_LOCK_NAME)):
        folder = old_lock.parent
        old_doc = folder / _OLD_DOC_NAME
        if not old_doc.exists():
            _migrate_lock_file(old_lock)
            lock_only += 1
            print(f"  lock migrated: {_rel(old_lock, root)}")
            continue
        if _is_git_tracked(old_doc, root):
            old_lock.unlink()
            orphan_locks += 1
            print(f"  human README kept, orphan lock removed: {_rel(old_doc, root)}")
            continue
        new_doc = folder / DOC_NAME
        old_doc.rename(new_doc)
        _migrate_lock_file(old_lock)
        renamed += 1
        print(f"  renamed: {_rel(old_doc, root)} -> {_rel(new_doc, root)}")
    create_root_map(root)
    print(f"  {renamed} generated README renamed, {lock_only} lock-only, "
          f"{orphan_locks} orphan locks removed")
    print(f"root map written: {_rel(root / DOC_NAME, root)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="readme_sync")
    parser.add_argument("--root", default=None, help="Repo root (default: cwd)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true",
                       help="Report the sync map; exit 1 if any stale/missing")
    group.add_argument("--list-stale", action="store_true",
                       help="Print one path per stale/missing folder")
    group.add_argument("--regen", nargs="?", const="", default=None,
                       metavar="PATH",
                       help="Regenerate AGENTS.md file(s): PATH for one folder, else all flagged")
    group.add_argument("--init", action="store_true",
                       help="Generate every missing/stale folder AGENTS.md + the root map")
    group.add_argument("--migrate", action="store_true",
                       help="Migrate old generated README.md (+.readme.lock) to AGENTS.md (+.agents.lock)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else Path.cwd()

    if args.check:
        return cmd_check(root)
    if args.list_stale:
        return cmd_list_stale(root)
    if args.regen is not None:
        path = args.regen if args.regen != "" else None
        return cmd_regen(root, path)
    if args.init:
        return cmd_init(root)
    if args.migrate:
        return cmd_migrate(root)
    parser.error("no command")
    return 2
