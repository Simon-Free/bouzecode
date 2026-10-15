"""Le internal LLM gateway sert `claude-*` en OpenAI-compatible : les compteurs de cache
arrivent sous les noms Anthropic, et les lire sous les seuls noms OpenAI faisait
disparaître "cached / cache-write" de la ligne de stats."""
from bouzecode.backend.agent.providers.backends.openrouter_stream import _usage_tokens


def test_openai_usage_splits_the_cached_prefix_out_of_prompt_tokens():
    """`prompt_tokens` inclut le préfixe caché : la ligne de stats l'ajoute déjà."""
    fresh, out, read, write = _usage_tokens({
        "prompt_tokens": 10_000,
        "completion_tokens": 500,
        "prompt_tokens_details": {"cached_tokens": 8_000},
    })
    assert (fresh, out, read, write) == (2_000, 500, 8_000, 0)


def test_anthropic_passthrough_usage_is_read_too():
    """LiteLLM en pass-through Anthropic : `input_tokens` EXCLUT déjà les cachés ; l'entrée
    rendue y rajoute l'écriture (convention de la chaîne, cf. registry)."""
    fresh, out, read, write = _usage_tokens({
        "input_tokens": 1_200,
        "output_tokens": 300,
        "cache_read_input_tokens": 29_000,
        "cache_creation_input_tokens": 306,
    })
    assert (fresh, out, read, write) == (1_506, 300, 29_000, 306)


def test_cache_write_is_no_longer_hardcoded_to_zero():
    """Le cache-write existait côté API mais était écrasé par un 0 en dur."""
    assert _usage_tokens({"cache_creation_input_tokens": 306})[3] == 306


def test_a_usage_without_any_cache_field_behaves_exactly_as_before():
    """Aucune régression pour openrouter/gpt-5 : champs absents = zéros."""
    assert _usage_tokens({"prompt_tokens": 42, "completion_tokens": 7}) == (42, 7, 0, 0)
    assert _usage_tokens({}) == (0, 0, 0, 0)


def test_an_inconsistent_total_never_goes_negative():
    """Un proxy qui rend un `prompt_tokens` plus petit que le caché ne doit pas
    produire un compteur négatif : on garde le total tel quel."""
    fresh, _, read, _ = _usage_tokens({
        "prompt_tokens": 100,
        "prompt_tokens_details": {"cached_tokens": 8_000},
    })
    assert (fresh, read) == (100, 8_000)
