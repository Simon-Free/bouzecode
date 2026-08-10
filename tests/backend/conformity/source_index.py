# [desc] AST index over the shipped src/ tree: which names are really used, and which env knobs are really read. [/desc]
"""Static facts about the shipped source tree, for the conformity tests in this folder.

Answers one question: **is this thing reachable from live code, or does its only
mention in `src/` happen to be the line that defines it?** The audit of 2026-07-27
found several mechanisms documented as active whose sole trace was their own `def`.

Two deliberate choices make the answer trustworthy:

- **An import is not a use.** `from x import y` is exactly how dead code keeps looking
  alive; counting it would make the whole index vacuous.
- **Import aliases ARE resolved.** `from t import iter_sse as _iter_sse` followed by
  `_iter_sse(resp)` is a real use of `iter_sse`. Without this the index reported two
  false positives, which is the fastest way to get a guard-rail test deleted.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ENV_KNOB_RE = re.compile(r"BOUZECODE_[A-Z0-9_]+\Z")


def repo_root() -> Path:
    """The checkout root, found by walking up to the folder holding `src/bouzecode`."""
    for base in Path(__file__).resolve().parents:
        if (base / "src" / "bouzecode").is_dir():
            return base
    raise RuntimeError("cannot locate the repository root from this test file")


SRC = repo_root() / "src"


@dataclass(frozen=True)
class Use:
    """One non-import mention of a name, and the function it sits in."""
    path: Path
    lineno: int
    function: str | None          # innermost enclosing def, None at module level


@dataclass(frozen=True)
class EnvKnob:
    """One `os.environ.get("BOUZECODE_…")` read, and the function that performs it."""
    variable: str
    path: Path
    lineno: int
    reader: str | None


def shipped_python_files() -> list[Path]:
    """Every .py under src/ that ships as live code (packaged test helpers excluded)."""
    return sorted(p for p in SRC.rglob("*.py") if "tests" not in p.parts)


def _alias_map(tree: ast.AST) -> dict[str, set[str]]:
    """{local alias: original name(s)} for every `import … as …` in a module."""
    aliases: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.asname:
                    aliases.setdefault(alias.asname, set()).add(alias.name.split(".")[-1])
    return aliases


class _SourceVisitor(ast.NodeVisitor):
    """Collects name uses and env-knob reads in one pass, tracking the enclosing def."""

    def __init__(self, path: Path, aliases: dict, uses: dict, knobs: list):
        self.path, self.aliases, self.uses, self.knobs = path, aliases, uses, knobs
        self.stack: list[str] = []

    # An import statement introduces no use — that is the point of the index.
    def visit_Import(self, node):
        return

    visit_ImportFrom = visit_Import

    def _record(self, identifier: str, lineno: int) -> None:
        enclosing = self.stack[-1] if self.stack else None
        for name in {identifier} | self.aliases.get(identifier, set()):
            self.uses.setdefault(name, []).append(Use(self.path, lineno, enclosing))

    def visit_Name(self, node):
        self._record(node.id, node.lineno)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        self._record(node.attr, node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in ("get", "getenv") and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str) \
                    and ENV_KNOB_RE.match(first.value):
                self.knobs.append(EnvKnob(first.value, self.path, node.lineno,
                                          self.stack[-1] if self.stack else None))
        self.generic_visit(node)

    def _visit_function(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function


class SourceIndex:
    """Every non-import reference and every env knob found in the shipped tree."""

    def __init__(self, uses: dict[str, list[Use]], knobs: list[EnvKnob]):
        self._uses, self._knobs = uses, knobs

    @classmethod
    def build(cls) -> "SourceIndex":
        uses: dict[str, list[Use]] = {}
        knobs: list[EnvKnob] = []
        for path in shipped_python_files():
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))
            _SourceVisitor(path, _alias_map(tree), uses, knobs).visit(tree)
        return cls(uses, knobs)

    def env_knobs(self) -> list[EnvKnob]:
        return list(self._knobs)

    def references(self, name: str, exclude: Path | None = None) -> list[Use]:
        """Every non-import mention of `name`, optionally ignoring one file."""
        return [u for u in self._uses.get(name, []) if exclude is None or u.path != exclude]

    def is_live(self, name: str, exclude: Path | None = None) -> bool:
        """True when `name` is used at module level, or inside a function something calls.

        The chain is followed ONE hop. A function reached only through another dead
        function still counts as live: a deliberate false NEGATIVE, chosen because a
        guard rail that cries wolf gets disabled, while one that under-reports still
        catches the flagrant cases it was written for.
        """
        for use in self.references(name, exclude):
            if use.function is None or self._uses.get(use.function):
                return True
        return False


@lru_cache(maxsize=1)
def source_index() -> SourceIndex:
    """Parsed once per process — ~280 files."""
    return SourceIndex.build()
