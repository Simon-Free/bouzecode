# [desc] E2E tests for symbol-aware folder descriptions, Read tool symbol param, and system prompt integration
# <tool_use name="FinalAnswer" id="r1"><param name="answer">E2E tests for symbol-aware folder descriptions, Read tool symbol param, and system prompt integration</param></tool_use> [/desc]
"""End-to-end tests exercising the full tool registry for symbol-aware reading."""
import pytest
from pathlib import Path

from bouzecode.backend.tools.ops.file_ops import _read
from bouzecode.backend.tools.folder_desc.tools import _get_folder_description
from bouzecode.backend.tools.schemas import TOOL_SCHEMAS
from bouzecode.backend.core.context import build_system_prompt


# ── Fixtures ────────────────────────────────────────────────────────────────

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

    def __init__(self, dsn: str):
        """Initialize with DSN."""
        self.dsn = dsn

    def connect(self):
        """Open a connection."""
        pass

    def query(self, sql: str):
        pass

    def close(self):
        """Shutdown gracefully."""
        pass
'''

JS_SRC = '''\
// [desc] Sample JS module for e2e testing [/desc]
/** Say hi */
function greetJs(name) {
  return `Hello ${name}`;
}

const helper = () => {
  return 42;
};

class JsService {
  /** Start the service */
  start() {
    console.log("started");
  }
  stop() {}
}

export function exported() {
  return true;
}
'''

TS_SRC = '''\
// [desc] Sample TS module for e2e testing [/desc]
/** Process items */
function processItems(items: string[]): number {
  return items.length;
}

class TsHandler {
  /** Handle request */
  handle(req: Request): Response {
    return new Response();
  }
}
'''


@pytest.fixture
def symbol_project(tmp_path: Path) -> Path:
    """Create a temp project with pre-described Python/JS/TS files."""
    pkg = tmp_path / "mylib"
    pkg.mkdir()
    (pkg / "core.py").write_text(PYTHON_SRC, encoding="utf-8")
    (pkg / "app.js").write_text(JS_SRC, encoding="utf-8")
    (pkg / "handler.ts").write_text(TS_SRC, encoding="utf-8")
    (pkg / "data.txt").write_text("not code\n", encoding="utf-8")
    return tmp_path


# ── GetFolderDescription ────────────────────────────────────────────────────

def test_e2e_folder_description_shows_python_symbols(symbol_project):
    result = _get_folder_description({"folder_path": str(symbol_project / "mylib")}, {})

    assert "Sample Python module" in result
    assert "def greet()" in result
    assert "Say hello to someone" in result
    assert "async" not in result or "def fetch_data()" in result
    assert "class DatabaseClient" in result
    assert "Client for database access" in result
    assert "def connect()" in result
    assert "def query()" in result
    assert "def close()" in result
    assert "[L" in result

    # data.txt is not a code file — should not appear in tree at all
    assert "data.txt" not in result


def test_e2e_folder_description_shows_js_symbols(symbol_project):
    ts_available = True
    try:
        import tree_sitter  # noqa: F401
    except ImportError:
        ts_available = False

    result = _get_folder_description({"folder_path": str(symbol_project / "mylib")}, {})

    if ts_available:
        assert "function greetJs()" in result
        assert "function helper()" in result
        assert "class JsService" in result
        assert "def start()" in result
        assert "function exported()" in result
    else:
        # Without tree-sitter, JS symbols are absent but file desc still shows
        assert "Sample JS module" in result


def test_e2e_folder_description_shows_ts_symbols(symbol_project):
    ts_available = True
    try:
        import tree_sitter  # noqa: F401
    except ImportError:
        ts_available = False

    result = _get_folder_description({"folder_path": str(symbol_project / "mylib")}, {})

    if ts_available:
        assert "function processItems()" in result
        assert "class TsHandler" in result
        assert "def handle()" in result
    else:
        assert "Sample TS module" in result


# ── Read with symbol= ──────────────────────────────────────────────────────

def test_e2e_read_symbol_toplevel(symbol_project):
    fp = str(symbol_project / "mylib" / "core.py")
    result = _read(fp, symbol="greet")

    assert "def greet" in result
    assert "Say hello to someone" in result
    assert "return f\"Hello {name}\"" in result
    # Should NOT contain other functions
    assert "fetch_data" not in result
    assert "class DatabaseClient" not in result


def test_e2e_read_symbol_async(symbol_project):
    fp = str(symbol_project / "mylib" / "core.py")
    result = _read(fp, symbol="fetch_data")

    assert "async def fetch_data" in result
    assert "Fetch raw bytes" in result
    assert "def greet" not in result


def test_e2e_read_symbol_class(symbol_project):
    fp = str(symbol_project / "mylib" / "core.py")
    result = _read(fp, symbol="DatabaseClient")

    assert "class DatabaseClient" in result
    assert "Client for database access" in result
    assert "def connect" in result
    assert "def query" in result
    assert "def close" in result
    # Should NOT include top-level functions
    assert "def greet" not in result


def test_e2e_read_symbol_nested_method(symbol_project):
    fp = str(symbol_project / "mylib" / "core.py")
    result = _read(fp, symbol="DatabaseClient.connect")

    assert "def connect" in result
    assert "Open a connection" in result
    # Should NOT include sibling methods
    assert "def query" not in result
    assert "def close" not in result


def test_e2e_read_symbol_not_found(symbol_project):
    fp = str(symbol_project / "mylib" / "core.py")
    result = _read(fp, symbol="nonexistent")
    assert "Error" in result
    assert "nonexistent" in result


def test_e2e_read_symbol_ignores_offset_limit(symbol_project):
    fp = str(symbol_project / "mylib" / "core.py")
    # Even with offset=100 and limit=1, symbol should override
    result = _read(fp, limit=1, offset=100, symbol="greet")
    assert "def greet" in result
    assert "Say hello to someone" in result


def test_e2e_read_symbol_line_numbers_are_correct(symbol_project):
    fp = str(symbol_project / "mylib" / "core.py")
    # greet starts at line 8 in PYTHON_SRC (after desc, docstring, import, blank, X=42, blank)
    result = _read(fp, symbol="greet")
    # Parse first line number from output (format: "     N\t...")
    first_line = result.strip().split("\n")[0]
    line_num = int(first_line.split("\t")[0].strip())
    # Read full file to verify
    content = (symbol_project / "mylib" / "core.py").read_text()
    lines = content.split("\n")
    assert "def greet" in lines[line_num - 1]


# ── Full workflow simulation ────────────────────────────────────────────────

def test_e2e_full_workflow(symbol_project):
    """Simulate agent workflow: GetFolderDescription → parse → Read symbols."""
    # Step 1: Get folder description
    tree = _get_folder_description({"folder_path": str(symbol_project / "mylib")}, {})

    # Step 2: Parse symbol names from tree output
    found_symbols = []
    for line in tree.split("\n"):
        stripped = line.strip()
        if stripped.startswith(("def ", "class ", "function ")):
            # Extract name: "def greet() -- doc  [L1-3]" → "greet"
            # or "class DatabaseClient -- doc  [L18-34]" → "DatabaseClient"
            after_keyword = stripped.split(None, 1)[1]  # drop "def"/"class"/"function"
            # Name ends at '(' or ' ' (classes have no parens)
            name = after_keyword.split("(")[0].split(" ")[0].split("\t")[0]
            found_symbols.append(name)

    assert "greet" in found_symbols
    assert "DatabaseClient" in found_symbols

    # Step 3: Read each discovered symbol
    fp = str(symbol_project / "mylib" / "core.py")
    for sym_name in found_symbols:
        if sym_name in ("greet", "fetch_data", "DatabaseClient"):
            result = _read(fp, symbol=sym_name)
            assert "Error" not in result
            assert len(result.strip()) > 0


# ── System prompt & schema integration ──────────────────────────────────────

@pytest.mark.skip(reason="Requires .bouzecode/profiles/ YAML (not in OSS worktree)")
def test_e2e_system_prompt_contains_symbol_rules():
    from pathlib import Path
    from bouzecode.backend.profiles import load_profiles_from_dir
    repo_root = Path(__file__).resolve().parents[4]
    extra = load_profiles_from_dir(repo_root / ".bouzecode" / "profiles")["default"].system_prompt_extra
    assert "Read(symbol=" in extra
    assert "symbol=" in extra
    assert "GetFolderDescription" in extra
    assert "Read(symbol=" not in build_system_prompt({})


def test_e2e_schema_has_symbol_param():
    read_schema = next(s for s in TOOL_SCHEMAS if s["name"] == "Read")
    props = read_schema["input_schema"]["properties"]
    assert "symbol" in props
    assert "string" == props["symbol"]["type"]
    assert "ClassName.method" in props["symbol"]["description"]


@pytest.mark.skip(reason="Requires .bouzecode/profiles/ YAML (not in OSS worktree)")
def test_e2e_embedded_template_mentions_symbol():
    from pathlib import Path
    from bouzecode.backend.profiles import load_profiles_from_dir
    repo_root = Path(__file__).resolve().parents[4]
    extra = load_profiles_from_dir(repo_root / ".bouzecode" / "profiles")["default"].system_prompt_extra
    assert "symbol" in extra


def test_e2e_tool_docs_xml_contains_symbol_param():
    from bouzecode.backend.xml_tool_protocol import build_tool_docs
    docs = build_tool_docs(TOOL_SCHEMAS)
    assert "symbol" in docs
    assert "ClassName.method" in docs
