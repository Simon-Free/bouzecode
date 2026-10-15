"""The Anthropic SDK migrated its HTTP layer from `httpx` to the `httpx2` package and
now REJECTS any client object coming from the other one:

    TypeError: Invalid `http_client` argument; `httpx.Client` is from the `httpx`
    package, but this SDK uses `httpx2`. Use `httpx2.Client` instead.

Our backend used to `import httpx` unconditionally, so the REPL crashed on its very
first turn for anyone with a recent SDK. The module we build the transport with must
be the one the SDK itself uses -- resolved from the SDK, not guessed.
"""

import types

from bouzecode.backend.agent.providers.backends.anthropic_client import (
    _httpx_module_for,
    build_anthropic_client,
)


def _fake_httpx_like(name: str) -> types.ModuleType:
    """A stand-in for httpx/httpx2: only what build_anthropic_client touches."""
    mod = types.ModuleType(name)

    class Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class Timeout:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class HTTPTransport:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    mod.Client = Client
    mod.Timeout = Timeout
    mod.HTTPTransport = HTTPTransport
    return mod


def test_resolves_httpx2_when_the_sdk_aliases_it_as_httpx():
    """Recent SDKs do `import httpx2 as httpx`: the attribute is named `httpx`
    but the module's real name is `httpx2`. We must return THAT module."""
    sdk_httpx = _fake_httpx_like("httpx2")
    base_client = types.ModuleType("anthropic._base_client")
    base_client.httpx = sdk_httpx

    assert _httpx_module_for(base_client) is sdk_httpx


def test_resolves_httpx2_when_the_sdk_imports_it_under_its_own_name():
    sdk_httpx = _fake_httpx_like("httpx2")
    base_client = types.ModuleType("anthropic._base_client")
    base_client.httpx2 = sdk_httpx

    assert _httpx_module_for(base_client) is sdk_httpx


def test_resolves_plain_httpx_for_older_sdks():
    sdk_httpx = _fake_httpx_like("httpx")
    base_client = types.ModuleType("anthropic._base_client")
    base_client.httpx = sdk_httpx

    assert _httpx_module_for(base_client) is sdk_httpx


def test_falls_back_to_a_real_import_when_the_sdk_exposes_nothing():
    """No httpx-ish module reachable from the SDK internals: we still must hand back
    a usable module rather than crash."""
    base_client = types.ModuleType("anthropic._base_client")

    resolved = _httpx_module_for(base_client)

    assert resolved is not None
    assert resolved.__name__.startswith("httpx")
    assert hasattr(resolved, "Client")


def test_build_anthropic_client_returns_a_usable_client():
    """Point of entry, exactly as the streaming backend calls it: it must not raise
    the TypeError above, and the keep-alive transport must still be wired in."""
    client = build_anthropic_client("test-key-not-used", None)

    assert client is not None
    assert client.api_key == "test-key-not-used"
