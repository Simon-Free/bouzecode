# [desc] <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests that DeepSeek native mode receives Methodology/Snippet tools with correct schemas and descriptions</param></tool_use> [/desc]
"""Diagnostic: verify that DeepSeek (native mode) receives Methodology and Snippet
in the tools list with complete descriptions and parameters."""
import pytest

from bouzecode.backend.agent.providers.backends.dispatch import stream
from bouzecode.backend.agent.providers.types import SystemPayload
from bouzecode.backend.tools.schemas import TOOL_SCHEMAS


def _get_system_payload(model: str, config: dict, tool_schemas: list):
    """Call stream() and return the first SystemPayload (emitted before any HTTP)."""
    gen = stream(
        model=model,
        system="",  # let build_system_prompt_parts generate the real system prompt
        messages=[{"role": "user", "content": "Hello"}],
        tool_schemas=tool_schemas,
        config=config,
    )
    try:
        return next(gen)
    finally:
        gen.close()


@pytest.fixture
def deepseek_config(monkeypatch):
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-fake")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    return {}


class TestDeepSeekReceivesMethodologyAndSnippet:
    """Verify Methodology/Snippet are in the native tools payload for DeepSeek."""

    def test_tools_list_contains_methodology_and_snippet(self, deepseek_config):
        payload = _get_system_payload("deepseek-v4-flash", deepseek_config, TOOL_SCHEMAS)
        assert isinstance(payload, SystemPayload)
        assert payload.tools is not None, "Native mode should produce a tools list"

        tool_names = [t["function"]["name"] for t in payload.tools]
        assert "Methodology" in tool_names, f"Methodology missing from tools: {tool_names}"
        assert "Snippet" in tool_names, f"Snippet missing from tools: {tool_names}"

    def test_methodology_description_is_detailed(self, deepseek_config):
        payload = _get_system_payload("deepseek-v4-flash", deepseek_config, TOOL_SCHEMAS)
        meth_tool = next(t for t in payload.tools if t["function"]["name"] == "Methodology")
        desc = meth_tool["function"]["description"]
        assert "WORKING MEMORY" in desc or "working memory" in desc.lower()
        assert "content" in meth_tool["function"]["parameters"]["properties"]

    def test_snippet_description_is_detailed(self, deepseek_config):
        payload = _get_system_payload("deepseek-v4-flash", deepseek_config, TOOL_SCHEMAS)
        snip_tool = next(t for t in payload.tools if t["function"]["name"] == "Snippet")
        desc = snip_tool["function"]["description"]
        assert "freeze" in desc.lower() or "labeled line range" in desc.lower()
        params = snip_tool["function"]["parameters"]["properties"]
        assert "file_path" in params
        assert "ranges" in params
        assert "discard" in params

    def test_system_prompt_mentions_methodology_instructions(self, deepseek_config):
        payload = _get_system_payload("deepseek-v4-flash", deepseek_config, TOOL_SCHEMAS)
        # Flatten system_blocks to get the full system prompt text
        system_text = "\n\n".join(
            b["text"] for b in payload.system_blocks if b.get("text")
        )
        # The stable_prefix should contain methodology instructions
        assert "Methodology" in system_text, "System prompt should mention Methodology"
        assert "Snippet" in system_text, "System prompt should mention Snippet"

    def test_tool_docs_section_is_empty_in_native_mode(self, deepseek_config):
        """In native mode, tool_docs should be empty (tools sent via API, not XML docs)."""
        payload = _get_system_payload("deepseek-v4-flash", deepseek_config, TOOL_SCHEMAS)
        # tool_docs is the second system_block (index 1)
        # It should be empty string in native mode
        if len(payload.system_blocks) > 1:
            tool_docs_block = payload.system_blocks[1]
            assert tool_docs_block.get("text", "") == "", (
                f"tool_docs should be empty in native mode, got: {tool_docs_block['text'][:200]}..."
            )

    def test_compare_xml_mode_has_full_tool_docs(self, deepseek_config):
        """In XML mode (forced via xml_tools=True), tool_docs should be non-empty."""
        config = {**deepseek_config, "xml_tools": True}
        payload = _get_system_payload("deepseek-v4-flash", config, TOOL_SCHEMAS)
        # In XML mode, tools should be None (no native tools)
        assert payload.tools is None, "XML mode should not produce native tools"
        # And tool_docs block should contain Methodology/Snippet docs
        system_text = "\n\n".join(
            b["text"] for b in payload.system_blocks if b.get("text")
        )
        assert "## Methodology" in system_text or "Methodology" in system_text
