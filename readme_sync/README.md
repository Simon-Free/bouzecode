# readme_sync/

Keeps every folder README in sync with the code it documents, detected by file hash, so an exploring agent descends a README map from root to the exact symbol with a minimum of reads and LLM calls.

---

## Subfolders

| Folder | Purpose |
|--------|---------|
| [prompts/](prompts/README.md) | System prompts: the regen contract, plus the reader (navigation) and writer (maintenance) protocols. |
| [tests/](tests/README.md) | Feature + CLI tests driving the real CLI/hook over temporary trees. |

---

## How it works

Each code folder owns a `README.md` (title + one-line purpose, `## Subfolders` map,
`## Module Reference` symbol index) and a sidecar `.readme.lock` (JSON manifest of
per-file `sha256` + `lines`). The **hash is the source of truth for freshness**: even
if a hook is missed, `--check` catches drift by recomputing hashes.

Folder states: **FRESH** (locks match) / **STALE** (hash differs, file added/removed,
or lock flagged stale) / **MISSING** (code folder with no README) / **ORPHAN**
(README with no code).

Code files are `.py` and `.js`: a front-end folder is documented like a Python one.

Ignored dirs: `.venv`, `node_modules`, `dist`, `.pytest_cache`, `deploy_build`,
`bin`, `.git`, `__pycache__`, `vendor` (third-party code shipped in-tree is not
ours to document).

---

## CLI

Root-agnostic: `--root <path>` (default = cwd) points the tool at any repo.

| Command | Effect |
|---------|--------|
| `python -m readme_sync --check [--root PATH]` | Print the sync map; exit 1 if any folder is STALE/MISSING, 0 if all fresh. |
| `python -m readme_sync --list-stale [--root PATH]` | Print one path per stale/missing folder (nothing else). |
| `python -m readme_sync --regen [PATH] [--root PATH]` | Regenerate READMEs. With a PATH: that folder only. Without: every flagged folder. One LLM call per folder, then the lock goes fresh and the parent Subfolders row is mirrored mechanically up to the root. |

Regen provider: reads `ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`
from the environment (any Anthropic-compatible gateway). Model override via `READMESYNC_MODEL`
(default `claude-sonnet-4-5`).

---

## Module Reference

| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | — | Package marker. |
| `__main__.py` | — | `python -m readme_sync` entry point → `cli.main`. |
| `states.py` | ~30 | `FolderState` enum + `FolderStatus` dataclass. |
| `hashing.py` | ~164 | Walk + ignore-list + sha256 manifest, lock read/write, `classify()`, `scan()`, `set_lock_stale()`. |
| `contract.py` | ~65 | `REQUIRED_SECTIONS`, `validate(md)`, `purpose_of(md)`. |
| `regen.py` | ~140 | The single LLM call: `regen_folder()` (write README + fresh lock + propagate). |
| `propagate.py` | ~120 | Mechanical (zero-LLM) parent `## Subfolders` table refresh: `propagate_up()`. |
| `hook.py` | ~66 | PostToolUse marker (zero LLM): reads a JSON payload on stdin, flips the edited file's folder lock to stale. |
| `cli.py` | ~65 | argparse: `--check` / `--list-stale` / `--regen`. |

---

## Reader / writer protocol

- **Reading code** (navigation): follow [prompts/reader.md](prompts/reader.md) —
  start at the root README, follow `## Subfolders` links down to the right folder,
  read its `## Module Reference`, then read a SINGLE symbol. Grep is a last resort.
- **Writing code** (maintenance): follow [prompts/writer.md](prompts/writer.md) —
  after editing code, the folder's `.readme.lock` flips `stale:true`; never trust a
  README whose lock says stale; run `--regen <folder>` to refresh.

---

## Stale marking at runtime (bouzecode)

The bouzecode runtime has **no live hook registry** (no PostToolUse harness). So
stale marking is wired as a **direct backend call** after the native `Write`/`Edit`
tools succeed, rather than through an external hook process.

`bouzecode.backend.context_manager.stale_hooks.install_stale_hooks()` wraps the
`Write` and `Edit` tool functions; on success it calls
`bouzecode.backend.context_manager.readme_stale.mark_readme_stale(file_path)`,
which reuses this package's own logic — `readme_sync.hook.should_mark_stale`
(no-op for the README itself, non-code files, or ignored dirs) and
`readme_sync.hashing.set_lock_stale` (flips the folder's `.readme.lock`, creating
it stale if missing). No logic is duplicated.

The call is a **silent, fast no-op** when it cannot run:
- opted out via `BOUZECODE_README_SYNC` set to `0`/`false`/`off`/`no` (ON by default);
- `readme_sync` not importable in the agent's runtime (gated by `find_spec`, and
  imported **lazily inside the function** — a module-level import once froze the
  whole fleet, commit `fa2fffe`);
- any error is swallowed — marking a README stale must never break an agent turn.

## Hook entry point (external harnesses / CLI)

`readme_sync.hook` still works as a standalone PostToolUse hook for any harness
that *does* run command hooks — a JSON payload on stdin:

```json
{"tool_name": "Edit", "tool_input": {"file_path": "/abs/path/to/edited.py"}}
```

```json
{
  "hooks": {
    "PostToolUse": [
      { "matcher": "Write|Edit",
        "hooks": [{ "type": "command", "command": "python -m readme_sync.hook" }] }
    ]
  }
}
```

Either path is fast (<200ms), never calls an LLM, ignores the README itself,
non-code files, and the ignore-list, and creates the lock (stale) if missing.
