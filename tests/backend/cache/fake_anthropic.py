# [desc] Fake Anthropic streaming provider with a prefix-cache simulator for token-billing tests. [/desc]
from __future__ import annotations

import inspect
import os

import pytest

from bouzecode.backend.agent.providers.types import (
    AssistantTurn,
    StreamStarted,
    TextChunk,
    UsageSnapshot,
)

# Calibrated on a real run of these very tests against the live gateway:
# turn 1 sent 43,265 cached chars and was billed cache_creation=13,293 tokens.
_CHARS_PER_TOKEN = 3.25

# What the provider's call contract is, verified against the real function at
# fixture setup (see _assert_signature_mirrors) instead of being frozen blindly.
_REPLY = "ok"


def _tokens(n_chars: int) -> int:
    return int(n_chars / _CHARS_PER_TOKEN)


def _content_len(content) -> int:
    """Chars of a wire message content (a str, or a list of content blocks)."""
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict):
                total += len(str(block.get("text", "") or ""))
                total += len(str(block.get("content", "") or ""))
            else:
                total += len(str(block))
        return total
    return len(str(content or ""))


class PrefixCache:
    """The server half of Anthropic's prompt cache, reduced to what it bills.

    Each `cache_control` block closes a cacheable PREFIX of the system payload.
    A later call is served from the LONGEST prefix already written whose bytes
    still match, so one byte of drift inside the prefix costs a re-write instead
    of a read — which is precisely what the cache tests assert on.
    """

    def __init__(self) -> None:
        self.written: list[str] = []
        self.calls: list[dict] = []

    def account(self, system_blocks: list, messages: list) -> tuple[int, int, int]:
        """Return (read_tokens, creation_tokens, fresh_tokens) for this call."""
        cached = ""
        prefixes: list[str] = []
        fresh_chars = 0
        for block in system_blocks:
            text = block.get("text", "") or ""
            if block.get("cache_control"):
                cached += text
                prefixes.append(cached)
            else:
                fresh_chars += len(text)
        read_chars = max(
            (len(p) for p in self.written if cached.startswith(p)), default=0
        )
        create_chars = len(cached) - read_chars
        self.written.extend(prefixes)
        fresh_chars += sum(_content_len(m.get("content")) for m in messages)
        read, create, fresh = _tokens(read_chars), _tokens(create_chars), _tokens(fresh_chars)
        self.calls.append({"read": read, "create": create, "fresh": fresh,
                           "cached_chars": len(cached)})
        return read, create, fresh


def make_fake_stream_anthropic(cache: PrefixCache, reply: str = _REPLY):
    """Build a `stream_anthropic` stand-in bound to *cache*.

    The signature mirrors the provider's on purpose (it sits on the very seam the
    StreamCapture spy wraps); `_assert_signature_mirrors` fails loudly if the
    provider gains a parameter, instead of letting dispatch raise a TypeError.
    """

    def stream_anthropic(api_key, model, system, messages, tool_schemas, config, *,
                         base_url=None, meth_delta="", cache_last=True, native_tools=None):
        read, create, fresh = cache.account(system, messages)
        in_tokens = fresh + create
        out_tokens = max(1, _tokens(len(reply)))
        yield StreamStarted()
        yield TextChunk(reply)
        yield UsageSnapshot(in_tokens, out_tokens, read, create)
        yield AssistantTurn(reply, [], in_tokens, out_tokens,
                            cache_read_tokens=read, cache_creation_tokens=create,
                            stop_reason="end_turn")

    return stream_anthropic


def _contract(fn) -> list[tuple]:
    return [(p.name, p.kind, p.default) for p in inspect.signature(fn).parameters.values()]


def _assert_signature_mirrors(fake, real) -> None:
    if _contract(fake) == _contract(inspect.unwrap(real)):
        return
    pytest.fail(
        "The fake stream_anthropic no longer mirrors the real one.\n"
        f"  provider: {[p[0] for p in _contract(inspect.unwrap(real))]}\n"
        f"  fake:     {[p[0] for p in _contract(fake)]}\n"
        "Mirror the new parameter explicitly in make_fake_stream_anthropic() — do NOT "
        "add **kwargs, that only hides the next drift."
    )


@pytest.fixture
def fake_anthropic(monkeypatch):
    """Serve these tests from a deterministic prefix-cache instead of the live API.

    Installed on BOTH seams the autouse network guard owns
    (`anthropic_stream.stream_anthropic` and `dispatch.stream_anthropic`), so the
    guard is honoured (no live call) rather than bypassed. Returns the
    `PrefixCache`, whose `.calls` records what each turn was billed.
    """
    from bouzecode.backend.agent.providers.backends import anthropic_stream as _a
    from bouzecode.backend.agent.providers.backends import dispatch as _d

    cache = PrefixCache()
    fake = make_fake_stream_anthropic(cache)
    _assert_signature_mirrors(fake, _a.stream_anthropic)
    monkeypatch.setattr(_a, "stream_anthropic", fake, raising=False)
    monkeypatch.setattr(_d, "stream_anthropic", fake, raising=False)
    # dispatch still reads credentials before streaming: the fake must not depend
    # on the machine having a key.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-hermetic-cache-tests")
    return cache
