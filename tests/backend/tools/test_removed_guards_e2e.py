# [desc] Conversation tests pinning the behaviour that survives the removal of the grep/glob guard and the out-of-worktree annotation. [/desc]
"""Three dead guards were removed. These conversations pin what did NOT change.

- `grep_guard.install_grep_guard()` was a documented no-op (its body was `pass`), so
  root-scoped Grep and Glob must keep returning matches exactly as before.
- The out-of-worktree hooks never refused anything: they PREFIXED a warning to the
  tool result and appended a line to `<ipc_dir>/out_of_worktree.jsonl` that no reader
  in the codebase ever consumed. The behaviour anyone actually depended on — the write
  happens, cross-repo action is never blocked — is what these tests hold.
- The "PLAN REQUIRED" gate left no string in the sources; nothing to pin here beyond
  the plan-mode message that replaced it, already covered in tests/backend/plan_mode/.
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
CLOSE = "C'est fait."


def _results(result, name):
    return [m["content"] for m in result.messages
            if m.get("role") == "tool" and m.get("name") == name]


def _make_repo(root):
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "service.py").write_text("def handler():\n    return 1\n", encoding="utf-8")
    (root / "README.md").write_text("# doc\n", encoding="utf-8")


def test_search_scoped_at_a_repo_root_still_returns_matches(tmp_path):
    """The removed guard used to be described as blocking root-scoped searches. It had
    already been a no-op for months: a Grep and a Glob aimed at a repository root come
    back with their matches, not with a refusal."""
    _make_repo(tmp_path)
    root = tmp_path.as_posix()
    mock = MockLLM([
        f'{METH}\n'
        f'<tool_use name="Grep" id="gr1"><param name="pattern">handler</param>'
        f'<param name="path">{root}</param></tool_use>\n'
        f'<tool_use name="Glob" id="gl1"><param name="pattern">*.py</param>'
        f'<param name="path">{root}</param></tool_use>',
        CLOSE,
    ])
    result = bouzecode(["explore this repo"], mock_llm=mock)

    grep_out = "\n".join(_results(result, "Grep"))
    glob_out = "\n".join(_results(result, "Glob"))
    assert "def handler" in grep_out
    assert "service.py" in glob_out
    for out in (grep_out, glob_out):
        assert "blocked" not in out.lower()
        assert "Error" not in out


def test_write_outside_an_isolated_worktree_succeeds_silently(tmp_path, monkeypatch):
    """An isolated agent (BOUZECODE_WORKTREE_ROOT armed) writing OUTSIDE its worktree:
    the file is written — that was never refused and still is not — and the result
    carries no harvest warning, since nothing in the codebase ever read the trace."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    ipc = tmp_path / "ipc"
    ipc.mkdir()
    monkeypatch.setenv("BOUZECODE_WORKTREE_ROOT", str(worktree))

    external = tmp_path / "elsewhere" / "temp_cross.py"
    external.parent.mkdir(parents=True, exist_ok=True)
    mock = MockLLM([
        f'{METH}\n<tool_use name="Write" id="w1">'
        f'<param name="file_path">{external.as_posix()}</param>'
        f'<param name="content">x = 1</param></tool_use>',
        CLOSE,
    ])
    result = bouzecode(["write the cross-repo file"], mock_llm=mock,
                       config_overrides={"_web_agent_dir": str(ipc)})

    assert external.read_text(encoding="utf-8") == "x = 1"   # never blocked
    write_out = "\n".join(_results(result, "Write"))
    assert "hors worktree" not in write_out
    assert "harvest" not in write_out
    assert not (ipc / "out_of_worktree.jsonl").exists()


def test_write_inside_an_isolated_worktree_is_unaffected(tmp_path, monkeypatch):
    """Control: the in-worktree case was silent before the removal and stays silent."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setenv("BOUZECODE_WORKTREE_ROOT", str(worktree))

    inside = worktree / "temp_inside.py"
    mock = MockLLM([
        f'{METH}\n<tool_use name="Write" id="w1">'
        f'<param name="file_path">{inside.as_posix()}</param>'
        f'<param name="content">y = 2</param></tool_use>',
        CLOSE,
    ])
    result = bouzecode(["write inside"], mock_llm=mock)

    assert inside.read_text(encoding="utf-8") == "y = 2"
    assert "hors worktree" not in "\n".join(_results(result, "Write"))


DEAD_MODULES = ("grep_guard", "out_of_worktree")


def _dead_identifiers(path: Path) -> list[str]:
    """Identifiers naming a removed guard: imports, calls, attribute access.

    Deliberately AST-based rather than a text grep. A grep also matches the COMMENTS
    that explain why a guard was deleted — and those comments are the point: without
    them the next reader re-adds the corpse. What must not survive is a live
    reference, which only the syntax tree can tell apart from prose.
    """
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, ast.Name):
            names.append(node.id)
    return [n for n in names if any(dead in n for dead in DEAD_MODULES)]


def test_the_removed_modules_are_really_gone():
    """No import of the deleted guards survives anywhere in the package — a leftover
    `from .grep_guard import ...` would crash every agent at startup, and the whole
    point of the deletion is that nobody optimises against a corpse again."""
    import bouzecode.backend.tools  # noqa: F401  (runs registration.py for real)

    pkg = Path(bouzecode.backend.tools.__file__).parent
    assert not (pkg / "grep_guard.py").exists()
    assert not (pkg / "out_of_worktree.py").exists()

    src = Path(bouzecode.backend.tools.__file__).parents[2]
    offenders = {
        str(p): dead for p in src.rglob("*.py") if (dead := _dead_identifiers(p))
    }
    assert offenders == {}, offenders
