# [desc] Tests that Read tool schema, profile templates, and XML docs expose the symbol parameter. [/desc]
"""Discoverability invariants for symbol-aware reading.

These are NOT conversation behaviours: the `symbol` param must appear in the Read
tool schema / system-prompt template / XML tool docs so the model learns it exists.
The harness stubs tool schemas, so this is checked directly on the static data.
"""
import pytest
from bouzecode.backend.tools.schemas import TOOL_SCHEMAS


def test_read_schema_has_symbol_param():
    read_schema = next(s for s in TOOL_SCHEMAS if s["name"] == "Read")
    props = read_schema["input_schema"]["properties"]
    assert "symbol" in props
    assert props["symbol"]["type"] == "string"
    assert "ClassName.method" in props["symbol"]["description"]


@pytest.mark.skip(reason="Requires .bouzecode/profiles/ YAML (not in OSS worktree)")
def test_embedded_template_mentions_symbol():
    # The `symbol` read hint now lives in the default code profile, not the noyau template.
    from pathlib import Path
    from bouzecode.backend.profiles import load_profiles_from_dir
    repo_root = Path(__file__).resolve().parents[4]
    extra = load_profiles_from_dir(repo_root / ".bouzecode" / "profiles")["default"].system_prompt_extra
    assert "symbol" in extra


def test_tool_docs_xml_contains_symbol_param():
    from bouzecode.backend.xml_tool_protocol import build_tool_docs
    docs = build_tool_docs(TOOL_SCHEMAS)
    assert "symbol" in docs
    assert "ClassName.method" in docs
