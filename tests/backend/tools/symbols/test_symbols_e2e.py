# [desc] Conversation feature tests for symbol-aware reading: Read(symbol=) and GetFolderDescription through bouzecode(). [/desc]
"""Symbol behaviour exercised through real bouzecode() conversations.

Replaces the direct-call tests in test_symbols.py / test_symbol_not_found_message.py
and the behaviour half of test_symbols_feature.py: instead of calling _read() /
_get_folder_description() directly, the (mocked) model issues the tool calls and we
assert on the tool results that land in the conversation transcript.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
# Closing reply: PLAIN TEXT, no tool call. A Methodology/Snippet-only batch is
# bookkeeping — since b83ade94 it never closes the session, it earns a
# continue-nudge. Only FinalAnswer or a tool-call-free reply closes.
CLOSE = "C'est fait."


@pytest.fixture(autouse=True)
def _enable_gfd():
    from bouzecode.backend.core.tool_registry import enable_tool
    enable_tool("GetFolderDescription")


PYTHON_SRC = '''\
# [desc] Sample Python module for e2e testing [/desc]
"""Sample module."""
import os

X = 42


def greet(name: str) -> str:
    """Say hello to someone."""
    return f"Hello {name}"


async def fetch_data(url: str) -> bytes:
    """Fetch raw bytes from url."""
    return b""


class DatabaseClient:
    """Client for database access."""

    def connect(self):
        """Open a connection."""
        pass

    def close(self):
        """Shutdown gracefully."""
        pass
'''

JS_SRC = '''\
// [desc] Sample JS module for e2e testing [/desc]
function greetJs(name) { return `Hi ${name}`; }
class JsService { start() {} stop() {} }
'''


@pytest.fixture
def symbol_project(tmp_path):
    pkg = tmp_path / "mylib"
    pkg.mkdir()
    (pkg / "core.py").write_text(PYTHON_SRC, encoding="utf-8")
    (pkg / "app.js").write_text(JS_SRC, encoding="utf-8")
    (pkg / "data.txt").write_text("not code\n", encoding="utf-8")
    return tmp_path


def _tool_result(result, name):
    msgs = [m for m in result.messages if m.get("role") == "tool" and m.get("name") == name]
    assert msgs, f"no {name} tool result in transcript"
    return msgs[0]["content"]


def _read_symbol(file_path, symbol):
    """Drive a Read(symbol=) through a conversation; return the Read tool result.

    A Read yields a snippetable result, so turn 2 emits Snippet(discard) to satisfy
    enforcement (mirrors the real loop)."""
    read = (f'<tool_use name="Read" id="r1"><param name="file_path">{file_path}</param>'
            f'<param name="symbol">{symbol}</param></tool_use>')
    snip = (f'<tool_use name="Snippet" id="s1"><param name="discard">true</param>'
            f'<param name="file_path">{file_path}</param></tool_use>')
    mock = MockLLM([f"{METH}\n{read}", f"{METH}\n{snip}", CLOSE])
    result = bouzecode([f"read {symbol}"], mock_llm=mock)
    return _tool_result(result, "Read")


def _describe_folder(folder, monkeypatch):
    monkeypatch.setattr(
        "bouzecode.backend.tools.folder_desc.analyzer._call_llm_for_description",
        lambda *a, **k: "stub description",
    )
    gfd = (f'<tool_use name="GetFolderDescription" id="g1">'
           f'<param name="folder_path">{folder}</param></tool_use>')
    mock = MockLLM([f"{METH}\n{gfd}", CLOSE])
    result = bouzecode(["describe folder"], mock_llm=mock)
    return _tool_result(result, "GetFolderDescription")


# ── Read(symbol=) ────────────────────────────────────────────────────────────

def test_read_symbol_toplevel(symbol_project):
    out = _read_symbol(symbol_project / "mylib" / "core.py", "greet")
    assert "def greet" in out
    assert "Say hello to someone" in out
    assert "fetch_data" not in out
    assert "class DatabaseClient" not in out


def test_read_symbol_async(symbol_project):
    out = _read_symbol(symbol_project / "mylib" / "core.py", "fetch_data")
    assert "async def fetch_data" in out
    assert "def greet" not in out


def test_read_symbol_class(symbol_project):
    out = _read_symbol(symbol_project / "mylib" / "core.py", "DatabaseClient")
    assert "class DatabaseClient" in out
    assert "def connect" in out
    assert "def close" in out
    assert "def greet" not in out


def test_read_symbol_nested_method(symbol_project):
    out = _read_symbol(symbol_project / "mylib" / "core.py", "DatabaseClient.connect")
    assert "def connect" in out
    assert "Open a connection" in out
    assert "def close" not in out


def test_read_symbol_not_found_serves_the_file_and_lists_the_real_symbols(symbol_project):
    """Symbole absent : le fichier entier est servi (le tour n'est pas perdu) ET les
    symboles réellement présents sont nommés pour que le prochain Read vise juste."""
    out = _read_symbol(symbol_project / "mylib" / "core.py", "nonexistent")

    assert "not found" in out and "nonexistent" in out, "l'absence doit rester dite"
    assert "Available symbols:" in out
    assert "greet" in out
    assert "DatabaseClient" in out
    assert "DatabaseClient.connect" in out
    # Ce qui a changé : le contenu arrive dans le MÊME tour, numéroté.
    assert "def greet" in out and "class DatabaseClient" in out
    assert "     1\t" in out, "le fichier est servi depuis sa première ligne, numérotée"


def test_read_symbol_on_syntax_error_file_degrades_gracefully(symbol_project):
    """Un fichier qui ne parse pas n'expose aucun symbole : on sert quand même sa source,
    en disant qu'aucun symbole n'a pu être détecté — jamais un crash, jamais un tour vide."""
    broken = symbol_project / "mylib" / "broken.py"
    broken.write_text("def broken(\n", encoding="utf-8")

    out = _read_symbol(broken, "broken")

    assert "not found" in out
    assert "Available symbols: (no symbols detected)" in out
    assert "def broken(" in out, "la source illisible par l'AST est servie telle quelle"


# ── GetFolderDescription ─────────────────────────────────────────────────────

def test_folder_description_shows_python_symbols(symbol_project, monkeypatch):
    out = _describe_folder(symbol_project / "mylib", monkeypatch)
    assert "Sample Python module" in out
    assert "def greet()" in out
    assert "Say hello to someone" in out
    assert "class DatabaseClient" in out
    assert "def connect()" in out
    assert "[L" in out
    assert "data.txt" not in out  # non-code excluded


def test_folder_description_js_symbols_when_tree_sitter_available(symbol_project, monkeypatch):
    try:
        import tree_sitter  # noqa: F401
    except ImportError:
        pytest.skip("tree_sitter not installed")
    out = _describe_folder(symbol_project / "mylib", monkeypatch)
    assert "function greetJs()" in out
    assert "class JsService" in out


# ── Full workflow ────────────────────────────────────────────────────────────

def test_full_workflow_describe_then_read(symbol_project, monkeypatch):
    """Describe the folder, then read a symbol surfaced by the description."""
    tree = _describe_folder(symbol_project / "mylib", monkeypatch)
    assert "def greet()" in tree
    out = _read_symbol(symbol_project / "mylib" / "core.py", "greet")
    assert "def greet" in out and "Error" not in out


# ── System prompt wiring (observed on the wire) ──────────────────────────────

def test_symbol_rules_reach_the_model_system_prompt():
    """Symbol-reading guidance lives in the default code profile (injected at depth 0
    by dispatch), not in the shared noyau."""
    from pathlib import Path
    from bouzecode.backend.profiles import load_profiles_from_dir
    from bouzecode.backend.core.context import build_system_prompt_parts

    repo_root = Path(__file__).resolve().parents[4]
    extra = load_profiles_from_dir(repo_root / ".bouzecode" / "profiles")["default"].system_prompt_extra
    assert "Read(symbol=" in extra
    assert "symbol=" in extra
    assert "Read(symbol=" not in build_system_prompt_parts()[0]
