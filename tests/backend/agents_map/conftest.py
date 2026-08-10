# [desc] Shared fixtures for the code-map tests: a two-file package and a call-counting fake LLM. [/desc]
from __future__ import annotations

from pathlib import Path

import pytest

from bouzecode.backend.tools.agents_map import manifest, regen

GOOD_MAP = """\
# pkg/

Deux fonctions de démonstration.

## Entry Points

| Function | File | Description |
|----------|------|-------------|
| `alpha()` | alpha.py | Point d'entrée. |

## Main Call Graph

```
alpha()                     [alpha.py]
 └── beta()                 [beta.py]
```

## Module Reference

| File | Lines | Purpose |
|------|-------|---------|
| `alpha.py` | 2 | Public: `alpha()`. |
| `beta.py` | 2 | Public: `beta()`. |

## External Dependencies

| Module | Functions used |
|--------|----------------|
| `os` | `getcwd()` |
"""


BAD_NESTING = GOOD_MAP.replace(
    "alpha()                     [alpha.py]\n └── beta()                 [beta.py]",
    "beta()                      [beta.py]\n └── alpha()                [alpha.py]",
)


class FakeLLM:
    """Un client qui compte ses appels et rend les documents imposés, dans l'ordre."""

    def __init__(self, *replies: str):
        self.calls: list[str] = []
        self.replies = list(replies) or [GOOD_MAP]
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs["messages"][0]["content"])
        text = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return type("R", (), {"content": [type("B", (), {"type": "text", "text": text})()]})()


@pytest.fixture
def pkg(tmp_path):
    folder = tmp_path / "pkg"
    folder.mkdir()
    (folder / "alpha.py").write_text("def alpha():\n    beta()\n")
    (folder / "beta.py").write_text("def beta():\n    return 1\n")
    return folder


def _write_fresh_map(folder: Path, model: str = "test-model") -> None:
    body = regen.compose(GOOD_MAP, regen.symbols_manifest(folder, model))
    (folder / manifest.SYMBOLS_DOC).write_text(body, encoding="utf-8")


@pytest.fixture
def fake_llm():
    """Fabrique un client factice ; chaque appel supplementaire rend la reponse suivante."""
    return FakeLLM


@pytest.fixture
def fresh_map():
    """Ecrit une carte conforme et a jour dans un dossier."""
    return _write_fresh_map


@pytest.fixture
def bad_nesting_map():
    """Une carte dont le graphe pretend que beta() appelle alpha()."""
    return BAD_NESTING


@pytest.fixture
def good_map():
    """Une carte conforme au contrat."""
    return GOOD_MAP
