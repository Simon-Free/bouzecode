# [desc] E2E test verifying system prompt builds without errors and reaches the model wire correctly
# <tool_use name="FinalAnswer" id="f1"><param name="answer">E2E test verifying system prompt builds without errors and reaches the model wire correctly</param></tool_use> [/desc]
"""System-prompt build invariants observed through a real bouzecode() conversation.

Replaces:
  - test_system_prompt_format.py (build_system_prompt renders without KeyError on
    template curly braces),
  - test_get_memory_context.py (build_system_prompt_parts / get_memory_context don't
    crash and return strings),
  - test_code_discovery_prompt.py (the Read(symbol=) / code-discovery guidance is in
    the prompt — the remainder is already covered by
    agent_loop/e2e/test_e2e_token_optimizations.py::TestCodeDiscoveryPrompt and
    tools/symbols/test_symbols_e2e.py::test_symbol_rules_reach_the_model_system_prompt).

These were trivial "the build doesn't blow up" regressions. Building the REAL prompt
and running it through a conversation exercises the same code path end-to-end and
proves the rendered text actually reaches the model (no unresolved {placeholders},
no KeyError/NameError), which the isolated build-only tests did not.
"""
from __future__ import annotations

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.core.context import build_system_prompt_parts

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


def test_real_system_prompt_builds_and_reaches_the_model():
    """build_system_prompt_parts renders cleanly and the text lands on the wire."""
    stable, volatile = build_system_prompt_parts({})
    assert isinstance(stable, str) and isinstance(volatile, str)
    real_prompt = stable + volatile

    mock = MockLLM([f"Hi!\n{METH}"])
    bouzecode(["hi"], mock_llm=mock, system_prompt=real_prompt)

    payload = str(mock.recorded_calls[0])
    # Identity rendered (proves the template was filled, no KeyError path).
    assert "Bouzecode" in payload
    # No unresolved template placeholders survived onto the wire.
    assert "{platform}" not in payload
    assert "{platform_hints}" not in payload
    assert "{claude_md}" not in payload
    # A noyau marker reaches the wire. Code-agent guidance (Read(symbol=) / code
    # discovery) now lives in the default profile, layered at depth 0 by dispatch —
    # covered by test_symbols_*.py and TestCodeDiscoveryPrompt, not here.
    assert "Un tour ressemble TOUJOURS" in payload
