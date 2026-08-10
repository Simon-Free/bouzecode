# [desc] Show unified diffs of files modified in the current turn for agent self-review. [/desc]
"""GetDiff tool: show file diffs for agent self-review."""
import difflib

from ...tools.state import get_file_snapshots


def _get_diff(file_path: str | None = None) -> str:
    snapshots = get_file_snapshots()
    if file_path:
        snapshots = {k: v for k, v in snapshots.items() if k == file_path}
    if not snapshots:
        return "No changes recorded." if not file_path else f"No changes for {file_path}"

    parts = []
    for path, snap in sorted(snapshots.items()):
        before = (snap.get("before") or "").splitlines(keepends=True)
        after = (snap.get("after") or "").splitlines(keepends=True)
        diff = difflib.unified_diff(before, after, fromfile=f"a/{path}", tofile=f"b/{path}")
        diff_text = "".join(diff)
        if diff_text:
            parts.append(diff_text)
        elif snap.get("is_new"):
            parts.append(f"--- /dev/null\n+++ b/{path}\n(new file)")
    return "\n".join(parts) if parts else "No changes recorded."
