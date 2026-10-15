"""Le transport OpenAI-compatible aplatissait les blocs system en une seule
string : tous les `cache_control` disparaissaient du wire, donc le gateway ne
cachait plus rien (0 cache read / 0 cache write, prompt facturé plein tarif à
chaque tour) et la ligne de stats perdait ses chiffres "cached / cache-write".
"""
from bouzecode.backend.agent.providers.backends.openrouter_stream import (
    _messages_to_openai,
    _system_content,
    _system_text,
)

EPHEMERAL = {"type": "ephemeral"}
BLOCKS = [
    {"type": "text", "text": "stable prefix", "cache_control": EPHEMERAL},
    {"type": "text", "text": "tool docs", "cache_control": EPHEMERAL},
    {"type": "text", "text": "volatile tail"},
]


def test_claude_keeps_the_cache_breakpoints_as_content_parts():
    """Le pass-through Anthropic (gateway/OpenRouter) ne voit les breakpoints que
    si le system reste une liste de content parts."""
    content = _system_content(BLOCKS, "claude-opus-5")
    assert isinstance(content, list)
    assert [p["text"] for p in content] == ["stable prefix", "tool docs", "volatile tail"]
    assert [p.get("cache_control") for p in content] == [EPHEMERAL, EPHEMERAL, None]
    assert all(p["type"] == "text" for p in content)


def test_an_openrouter_prefixed_claude_is_recognised_too():
    """OpenRouter préfixe le modèle : `anthropic/claude-...` cache aussi."""
    assert isinstance(_system_content(BLOCKS, "anthropic/claude-sonnet-4.5"), list)


def test_gpt5_still_gets_a_flat_string():
    """Azure/LiteLLM refuse un system structuré : aucune régression sur gpt-5*."""
    content = _system_content(BLOCKS, "gpt-5.6-thinking")
    assert content == _system_text(BLOCKS)
    assert isinstance(content, str)


def test_blocks_without_any_cache_control_stay_flat():
    """Sans breakpoint à préserver, on garde le comportement d'origine."""
    plain = [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
    assert _system_content(plain, "claude-opus-5") == "a\n\nb"


def test_an_already_flat_system_is_returned_untouched():
    assert _system_content("just a string", "claude-opus-5") == "just a string"


def test_empty_blocks_are_dropped_from_the_content_parts():
    blocks = [{"type": "text", "text": "", "cache_control": EPHEMERAL}, *BLOCKS]
    assert len(_system_content(blocks, "claude-opus-5")) == len(BLOCKS)


def test_the_payload_carries_the_structured_system_end_to_end():
    """Ce que reçoit réellement l'API : le message system garde ses parts."""
    msgs = _messages_to_openai(
        [{"role": "user", "content": "hello"}],
        _system_content(BLOCKS, "claude-opus-5"),
    )
    assert msgs[0]["role"] == "system"
    assert isinstance(msgs[0]["content"], list)
    assert msgs[0]["content"][0]["cache_control"] == EPHEMERAL
