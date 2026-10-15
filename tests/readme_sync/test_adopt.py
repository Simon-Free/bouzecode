# [desc] Tests that readme_sync generates AGENTS.md via LLM while leaving human README.md untouched. [/desc]
from __future__ import annotations

from pathlib import Path

from readme_sync.hashing import (
    FolderState,
    classify,
    read_lock,
    write_lock,
)
from readme_sync.propagate import create_root_map
from readme_sync.regen import regen_folder


DOC = "AGENTS.md"
README = "README.md"

HUMAN_README = """# Payments Engine

Handles card charges and refunds for the storefront.

## Installation

    pip install payments-engine
    export PAYMENTS_KEY=sk_live_xxx

Then run `payments serve`. See the ops runbook for on-call rotation.

## Notes for maintainers

Never log the raw card token. Refunds are idempotent by `charge_id`.
"""

GENERATED_OUTPUT = """# payments/

Handles card charges and refunds.

## Subfolders

| Folder | Purpose |
|--------|---------|
| [gateways/](gateways/AGENTS.md) | Payment gateway adapters. |

## Module Reference

- **charges.py** — Create and capture card charges.
- **refunds.py** — Idempotent refunds keyed by charge_id.
"""


class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, text):
        self._text = text
        self.calls = 0
        self.last_user_message = None

    def create(self, **kwargs):
        self.calls += 1
        self.last_user_message = kwargs["messages"][0]["content"]
        return _FakeResponse(self._text)


class _FakeClient:
    """Pure in-memory Anthropic-shaped client — no unittest.mock."""

    def __init__(self, text):
        self.messages = _FakeMessages(text)


def _make_folder_with_readme_and_code(tmp_path: Path) -> Path:
    folder = tmp_path / "payments"
    folder.mkdir()
    (folder / README).write_text(HUMAN_README, encoding="utf-8")
    (folder / "charges.py").write_text(
        '"""Create and capture card charges."""\n\ndef charge():\n    pass\n',
        encoding="utf-8",
    )
    (folder / "refunds.py").write_text(
        '"""Idempotent refunds keyed by charge_id."""\n\ndef refund():\n    pass\n',
        encoding="utf-8",
    )
    sub = folder / "gateways"
    sub.mkdir()
    (sub / "stripe.py").write_text(
        '"""Stripe gateway adapter."""\n\ndef send():\n    pass\n', encoding="utf-8"
    )
    (sub / DOC).write_text(
        "# gateways/\n\nPayment gateway adapters.\n", encoding="utf-8"
    )
    return folder


def test_regen_writes_agents_md_and_leaves_human_readme_untouched(tmp_path):
    """(a) A folder with a human README.md + code is documented into AGENTS.md via
    the LLM; the human README.md is passed as read-only context and preserved
    byte-for-byte."""
    folder = _make_folder_with_readme_and_code(tmp_path)
    before = (folder / README).read_bytes()

    client = _FakeClient(GENERATED_OUTPUT)
    result = regen_folder(folder, tmp_path, client=client)
    assert result == folder.resolve()

    # LLM was called and its README was passed as read-only context.
    assert client.messages.calls == 1
    assert "Human README.md (read-only context" in client.messages.last_user_message
    assert "Never log the raw card token." in client.messages.last_user_message

    # AGENTS.md created with the model output.
    agents = (folder / DOC).read_text(encoding="utf-8")
    assert "Handles card charges and refunds." in agents
    assert "## Module Reference" in agents

    # Human README.md preserved byte-for-byte.
    assert (folder / README).read_bytes() == before

    # Lock written fresh (.agents.lock) => folder classifies FRESH.
    lock = read_lock(folder)
    assert lock is not None
    assert lock["stale"] is False
    assert lock["doc"] == DOC
    assert (folder / ".agents.lock").exists()
    assert classify(folder).state is FolderState.FRESH


ROOT_README = """# Demo Application

The main Demo application.

## Installation

    git clone ...
    uv sync

Run the app with `demo serve`.
"""


def test_create_root_map_writes_agents_md_and_keeps_human_readme(tmp_path):
    """(b) create_root_map writes the map into AGENTS.md and never touches the
    human root README.md."""
    root = tmp_path
    (root / README).write_text(ROOT_README, encoding="utf-8")
    readme_before = (root / README).read_bytes()

    sub = root / "services"
    sub.mkdir()
    (sub / "worker.py").write_text('"""Background worker."""\n', encoding="utf-8")
    (sub / DOC).write_text(
        "# services/\n\nBackground services.\n", encoding="utf-8"
    )

    out = create_root_map(root)
    assert out == (root / DOC)

    md = (root / DOC).read_text(encoding="utf-8")
    assert md.startswith(f"# {root.name}/")
    assert "# ./" not in md
    assert "## Subfolders" in md
    assert "[services/](services/AGENTS.md)" in md

    # Human README.md untouched byte-for-byte.
    assert (root / README).read_bytes() == readme_before


def test_create_root_map_upserts_into_existing_agents_md(tmp_path):
    """An existing AGENTS.md keeps its human H1 + prose; create_root_map only
    upserts the ## Subfolders map."""
    root = tmp_path
    (root / DOC).write_text(ROOT_README, encoding="utf-8")

    sub = root / "services"
    sub.mkdir()
    (sub / "worker.py").write_text('"""Background worker."""\n', encoding="utf-8")
    (sub / DOC).write_text(
        "# services/\n\nBackground services.\n", encoding="utf-8"
    )

    create_root_map(root)
    md = (root / DOC).read_text(encoding="utf-8")

    assert "# Demo Application" in md
    assert "# ./" not in md
    assert "The main Demo application." in md
    assert "uv sync" in md
    assert "## Subfolders" in md
    assert "[services/](services/AGENTS.md)" in md


def test_regen_replaces_existing_agents_md_via_llm(tmp_path):
    """(c) A folder with a generated AGENTS.md + lock, whose code changed, is
    regenerated via the LLM (fake client); AGENTS.md is replaced by the output."""
    folder = tmp_path / "widgets"
    folder.mkdir()
    (folder / DOC).write_text("# widgets/\n\nOld generated doc.\n", encoding="utf-8")
    py = folder / "widget.py"
    py.write_text('"""Widget model v1."""\n', encoding="utf-8")

    write_lock(folder, stale=False)
    assert read_lock(folder) is not None

    py.write_text('"""Widget model v2 with more fields."""\n', encoding="utf-8")

    client = _FakeClient("# widgets/\n\nRenders widgets.\n\n## Module Reference\n\n- **widget.py** — Widget model.\n")
    regen_folder(folder, tmp_path, client=client)

    assert client.messages.calls == 1
    md = (folder / DOC).read_text(encoding="utf-8")
    assert "Renders widgets." in md
    assert "Old generated doc." not in md
