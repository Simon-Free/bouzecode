# [desc] Frontmatter manifest for SYMBOLS.md/AGENTS.md: per-file sha256, freshness verdict, deterministic rendering. [/desc]
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from .prompts import CONTRACT_VERSION

SYMBOLS_DOC = "SYMBOLS.md"
AGENTS_DOC = "AGENTS.md"
SHA_LEN = 12

_DEFAULT_EXTS = ".py,.js,.jsx,.ts,.tsx,.html,.css"
_IGNORE_DIRS = {
    ".venv", ".venv-ui", "venv", "env", "node_modules", "dist", "build", "vendor",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", "htmlcov",
    "deploy_build", "bin", ".git", "__pycache__", ".idea", ".vscode", "site-packages",
}
_DISABLED = {"0", "false", "off", "no"}


def feature_enabled() -> bool:
    """The single global escape hatch, shared with the legacy push hook."""
    for var in ("BOUZECODE_AGENTS_MAP", "BOUZECODE_README_SYNC"):
        if os.environ.get(var, "").strip().lower() in _DISABLED:
            return False
    return True


def code_exts() -> set[str]:
    raw = os.environ.get("BOUZECODE_AGENTS_MAP_EXTS") or _DEFAULT_EXTS
    return {e.strip() for e in raw.split(",") if e.strip()}


def code_files(folder: Path) -> list[Path]:
    """Direct code files of a folder, sorted by name. Never recursive."""
    exts = code_exts()
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix in exts),
        key=lambda p: p.name,
    )


def is_ignored_dir(path: Path) -> bool:
    return (
        path.name in _IGNORE_DIRS
        or path.name.endswith(".egg-info")
        or (path / "pyvenv.cfg").exists()
    )


def iter_code_folders(root: Path):
    """Every folder under root holding at least one direct code file."""
    stack = [root]
    while stack:
        folder = stack.pop()
        if code_files(folder):
            yield folder
        for child in sorted(folder.iterdir(), key=lambda p: p.name):
            if child.is_dir() and not is_ignored_dir(child):
                stack.append(child)


def sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:SHA_LEN]


def line_count(path: Path) -> int:
    """Lines as ``wc -l`` counts them: a trailing newline does not open a line."""
    data = path.read_bytes()
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def folder_manifest(folder: Path) -> dict[str, dict]:
    return {
        p.name: {"sha256": sha_of(p), "lines": line_count(p)}
        for p in code_files(folder)
    }


def tree_sha(root: Path) -> str:
    """sha256 of the sorted list of code-folder paths — the repo's tree shape."""
    paths = sorted(
        str(f.relative_to(root)).replace("\\", "/") for f in iter_code_folders(root)
    )
    return hashlib.sha256("\n".join(paths).encode()).hexdigest()[:SHA_LEN]


# -- frontmatter -----------------------------------------------------------

_FM = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


def split_frontmatter(text: str) -> tuple[dict, str]:
    """``(manifest, body)``. A document with no frontmatter yields ``({}, text)``."""
    m = _FM.match(text)
    if not m:
        return {}, text
    return _parse_manifest(m.group(1)), text[m.end():]


def _parse_manifest(block: str) -> dict:
    data: dict = {}
    files: dict[str, dict] = {}
    in_files = False
    for line in block.splitlines():
        if not line.strip():
            continue
        if line.startswith("  ") and in_files:
            name, _, rest = line.strip().partition(":")
            entry = {}
            for part in rest.strip().strip("{}").split(","):
                k, _, val = part.partition(":")
                k, val = k.strip(), val.strip()
                if k:
                    entry[k] = int(val) if val.isdigit() else val
            files[name] = entry
            continue
        in_files = False
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if key == "files":
            in_files = True
            continue
        data[key] = int(val) if val.isdigit() else val
    if in_files or files:
        data["files"] = files
    return data


def render_frontmatter(manifest: dict) -> str:
    """Deterministic YAML: fixed key order, files sorted, no timestamp."""
    lines = ["---"]
    for key in ("symbols_map", "agents_map", "model", "contract", "tree_sha256", "folders"):
        if key in manifest:
            lines.append(f"{key}: {manifest[key]}")
    files = manifest.get("files")
    if files is not None:
        lines.append("files:")
        for name in sorted(files):
            e = files[name]
            lines.append(f"  {name}: {{sha256: {e['sha256']}, lines: {e['lines']}}}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# -- freshness -------------------------------------------------------------

def staleness(doc: Path, current: dict, model: str) -> list[str]:
    """Why ``doc`` is out of phase with ``current``. Empty list = serve as is."""
    if not doc.exists():
        return ["missing"]
    recorded, _ = split_frontmatter(doc.read_text(encoding="utf-8"))
    if not recorded:
        return ["no frontmatter manifest"]
    if recorded.get("contract") != CONTRACT_VERSION:
        return ["contract version changed"]
    if recorded.get("model") != model:
        return [f"model changed: {recorded.get('model')} -> {model}"]
    if "tree_sha256" in current:
        if recorded.get("tree_sha256") != current["tree_sha256"]:
            return ["tree shape changed"]
        return []
    return _file_diff(recorded.get("files", {}), current.get("files", {}))


def _file_diff(recorded: dict, current: dict) -> list[str]:
    reasons = []
    for name in sorted(set(current) - set(recorded)):
        reasons.append(f"new file: {name}")
    for name in sorted(set(recorded) - set(current)):
        reasons.append(f"deleted file: {name}")
    for name in sorted(set(recorded) & set(current)):
        if recorded[name].get("sha256") != current[name]["sha256"]:
            reasons.append(f"hash changed: {name}")
    return reasons
