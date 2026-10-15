# [desc] Tests that build_tool_docs documents only the listed tools in full and indexes the others in one line each. [/desc]
"""Tool docs restricted to a core set: every tool stays visible, only the core pays full price.

Focus sends ~120 tools; documenting all of them in XML cost ~24k tokens per LLM call
(audit 2026-09-29). With ``full_doc_names`` the listed tools keep their full section and
every other tool is reduced to one index line (signature + first sentence), so no tool
becomes invisible to the model.
"""
from __future__ import annotations

from bouzecode.backend.agent.providers.backends.dispatch import stream
from bouzecode.backend.xml_tool_protocol import XmlToolStreamParser, build_tool_docs

READ_SCHEMA = {
    "name": "Read",
    "description": "Read a file from disk.",
    "input_schema": {
        "type": "object",
        "properties": {"file_path": {"type": "string", "description": "Absolute file path"}},
        "required": ["file_path"],
    },
}

GENERATE_CSV_SCHEMA = {
    "name": "generate_csv",
    "description": "Génère un fichier CSV téléchargeable. Détail très long qui ne doit pas "
                   "apparaître dans l'index compact.",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "Nom du fichier"},
            "rows": {"type": "array", "description": "Lignes"},
            "sep": {"type": "string", "description": "Séparateur"},
        },
        "required": ["filename", "rows"],
    },
}


def test_without_a_core_set_every_tool_is_documented_in_full():
    assert build_tool_docs([READ_SCHEMA, GENERATE_CSV_SCHEMA], None) == build_tool_docs(
        [READ_SCHEMA, GENERATE_CSV_SCHEMA])
    assert "## generate_csv" in build_tool_docs([READ_SCHEMA, GENERATE_CSV_SCHEMA])


def test_core_tool_keeps_its_full_section_with_example():
    docs = build_tool_docs([READ_SCHEMA, GENERATE_CSV_SCHEMA], {"Read"})
    assert "## Read" in docs
    assert "Absolute file path" in docs
    assert '<tool_use name="Read"' in docs


def test_non_core_tool_is_indexed_with_its_signature_and_first_sentence_only():
    docs = build_tool_docs([READ_SCHEMA, GENERATE_CSV_SCHEMA], {"Read"})
    assert "## generate_csv" not in docs
    assert "- generate_csv(filename: string, rows: array, sep?: string) — " \
           "Génère un fichier CSV téléchargeable." in docs
    assert "Détail très long" not in docs
    assert "Séparateur" not in docs


def test_indexed_tools_are_still_callable_through_the_documented_protocol():
    docs = build_tool_docs([READ_SCHEMA, GENERATE_CSV_SCHEMA], {"Read"})
    parser = XmlToolStreamParser()
    calls = [item for item in parser.feed(docs) if isinstance(item, dict)] + parser.finalize()
    assert [c for c in calls if c["name"] == "_XmlParseError"] == []
    assert [c["name"] for c in calls if c["name"] == "generate_csv"] == []


def test_stream_applies_the_core_set_from_config(monkeypatch):
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-fake")
    generator = stream(
        model="deepseek-v4-flash",
        system="",
        messages=[{"role": "user", "content": "Hello"}],
        tool_schemas=[READ_SCHEMA, GENERATE_CSV_SCHEMA],
        config={"xml_tools": True, "tool_docs_full_names": {"Read"}},
    )
    payload = next(generator)
    generator.close()
    system_text = "\n\n".join(block["text"] for block in payload.system_blocks)
    assert "## Read" in system_text
    assert "## generate_csv" not in system_text
    assert "- generate_csv(" in system_text
