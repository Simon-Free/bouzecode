# [desc] Helpers for test_methodology_cache_e2e: capture stream_anthropic inputs (no LLM mock), find methodology block, diagnose byte drifts. [/desc]
from __future__ import annotations

import copy
import inspect
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from bouzecode.backend.context_manager.methodology import _METHODOLOGY_HEADER


class StreamCapture:
    """Record (system_blocks, messages) per call to stream_anthropic.

    Deep-copied so later mutations from the live call don't corrupt snapshots.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def record(self, system_blocks, messages, meth_delta="") -> None:
        self.calls.append({
            "system_blocks": copy.deepcopy(system_blocks),
            "messages":      copy.deepcopy(messages),
            "meth_delta":    meth_delta,
        })


def _call_contract(func) -> list[tuple]:
    """(name, kind, default) per parameter — the part of a signature that decides
    whether a call still type-checks. Annotations are deliberately excluded: they
    can be reworded without changing how the function is called."""
    return [
        (p.name, p.kind, p.default)
        for p in inspect.signature(func).parameters.values()
    ]


def assert_mirrors(spy, real) -> None:
    """Fail here, naming the drift, when the spy stops mirroring what it wraps.

    The spy is a pass-through, so it must forward every argument the provider
    accepts. Neither easy option is acceptable: ``**kwargs`` forwards silently and
    lets the seam drift unnoticed, while a frozen explicit signature surfaces the
    drift as an opaque ``TypeError`` raised deep inside ``dispatch.stream`` (that is
    how ``native_tools`` showed up — looking like a provider regression). Mirroring
    explicitly AND checking the mirror gives the third option: an actionable message
    at fixture setup, before a single API call is made."""
    if _call_contract(spy) == _call_contract(real):
        return
    pytest.fail(
        "The StreamCapture spy no longer mirrors stream_anthropic().\n"
        f"  provider: {[p[0] for p in _call_contract(real)]}\n"
        f"  spy:      {[p[0] for p in _call_contract(spy)]}\n"
        "Mirror the new parameter in _wrapped and forward it explicitly — do NOT "
        "add **kwargs, that only hides the next drift."
    )


@pytest.fixture()
def capture(monkeypatch):
    """Wrap ``stream_anthropic`` with a recording pass-through so the real
    Anthropic API still serves the request while we snapshot its inputs."""
    from bouzecode.backend.agent.providers.backends import dispatch as _dispatch
    from bouzecode.backend.agent.providers.backends.anthropic_stream import stream_anthropic as _real

    cap = StreamCapture()

    # Signature mirrored on purpose (see assert_mirrors below). `_real` is the
    # module attribute, i.e. the conftest live-API gate, so the spy stays behind
    # the hermetic guard instead of reaching around it; `inspect.unwrap` looks
    # through that gate to the provider function the contract is checked against.
    def _wrapped(api_key, model, system, messages, tool_schemas, config, *,
                 base_url=None, meth_delta="", cache_last=True, native_tools=None):
        cap.record(system, messages, meth_delta)
        yield from _real(
            api_key, model, system, messages, tool_schemas, config,
            base_url=base_url, meth_delta=meth_delta, cache_last=cache_last,
            native_tools=native_tools,
        )

    assert_mirrors(_wrapped, inspect.unwrap(_real))
    monkeypatch.setattr(_dispatch, "stream_anthropic", _wrapped)
    return cap


def find_methodology_block(blocks: list[dict]) -> dict | None:
    for b in blocks:
        if isinstance(b, dict) and _METHODOLOGY_HEADER.strip() in (b.get("text") or ""):
            return b
    return None


def first_byte_diff(a: str, b: str) -> tuple[int, str, str] | None:
    """Offset of the first byte where a and b diverge, with ±40 chars of context.
    Returns None if one is a prefix of the other."""
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            return i, a[max(0, i - 40):i + 40], b[max(0, i - 40):i + 40]
    return None


def summarize_blocks(blocks: list[dict]) -> str:
    rows = []
    for i, b in enumerate(blocks):
        if not isinstance(b, dict):
            rows.append(f"  [{i}] (non-dict)")
            continue
        size = len(b.get("text") or "")
        cc = b.get("cache_control")
        marker = f" cache_control={cc}" if cc else " (no cache_control)"
        head = (b.get("text") or "")[:60].replace("\n", " ")
        rows.append(f"  [{i}] text chars={size:>6}{marker}  head={head!r}")
    return "\n".join(rows)


def dump_turn(label: str, turn, call: dict) -> None:
    print(
        f"\n=== {label} ===\n"
        f"  usage: in={turn.in_tokens:,} "
        f"cache_read={turn.cache_read_tokens:,} "
        f"cache_create={turn.cache_creation_tokens:,} "
        f"out={turn.out_tokens:,}\n"
        f"  meth_delta_chars={len(call.get('meth_delta', ''))}\n"
        f"  system_blocks:\n{summarize_blocks(call['system_blocks'])}"
    )


def assert_block_byte_identical(name: str, text1: str, text2: str) -> None:
    if text1 == text2:
        return
    diff = first_byte_diff(text1, text2)
    if diff is None:
        pytest.fail(
            f"{name} sizes differ (t1={len(text1)}, t2={len(text2)}) — "
            "one is a prefix of the other, cache cannot hit."
        )
    pytest.fail(
        f"{name} drifted between turns — first diff at offset {diff[0]}.\n"
        f"  t1 ctx: {diff[1]!r}\n"
        f"  t2 ctx: {diff[2]!r}"
    )
