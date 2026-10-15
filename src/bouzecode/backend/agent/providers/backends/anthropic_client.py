# [desc] Builds the Anthropic SDK client with a keep-alive httpx transport tuned for the gateway. [/desc]
from __future__ import annotations
import os


def _httpx_module_for(base_client_mod=None):
    """Return the httpx-compatible module the INSTALLED Anthropic SDK actually uses.

    Recent SDK releases vendor their HTTP layer as a separate `httpx2` package and
    reject any object coming from `httpx` (`_reject_httpx_object`). Both packages can
    be installed side by side during the transition, so the SDK itself is the only
    source of truth: we look at which module `anthropic._base_client` imported.
    """
    from types import ModuleType
    import importlib

    if base_client_mod is None:
        try:
            base_client_mod = importlib.import_module("anthropic._base_client")
        except Exception:
            base_client_mod = None

    if base_client_mod is not None:
        candidates = [
            value
            for value in vars(base_client_mod).values()
            if isinstance(value, ModuleType)
            and getattr(value, "__name__", "").startswith("httpx")
        ]
        # Prefer a module that really exposes a client; fall back to any httpx* module
        # (test doubles may be minimal).
        for value in candidates:
            if hasattr(value, "Client"):
                return value
        if candidates:
            return candidates[0]

    for name in ("httpx2", "httpx"):
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    raise ImportError("neither 'httpx2' nor 'httpx' is installed")


def build_anthropic_client(api_key: str, base_url: str | None, default_headers: dict | None = None):
    """Anthropic SDK client over an httpx transport with TCP keep-alive.

    The gateway sits behind a corporate gateway that silently drops idle connections
    mid-stream; keep-alive probes surface the drop as a real error the retry loop
    can act on instead of an infinite stall.
    """
    import anthropic as _ant
    import socket as _socket

    from bouzecode.backend.core.tls import httpx_verify

    _httpx = _httpx_module_for()

    # vérification TLS toujours active (bundle CA via SSL_CERT_FILE /
    # REQUESTS_CA_BUNDLE) ; PYTHONHTTPSVERIFY=0 n'est plus honoré.
    verify = httpx_verify("gateway Anthropic")
    keepalive_opts = [(_socket.SOL_SOCKET, _socket.SO_KEEPALIVE, 1)]
    # Linux: TCP_KEEPIDLE. macOS: TCP_KEEPALIVE. Windows: neither.
    keepidle = getattr(_socket, "TCP_KEEPIDLE", getattr(_socket, "TCP_KEEPALIVE", None))
    if keepidle is not None:
        keepalive_opts.append((_socket.IPPROTO_TCP, keepidle, 30))
    if hasattr(_socket, "TCP_KEEPINTVL"):
        keepalive_opts.append((_socket.IPPROTO_TCP, _socket.TCP_KEEPINTVL, 10))
    if hasattr(_socket, "TCP_KEEPCNT"):
        keepalive_opts.append((_socket.IPPROTO_TCP, _socket.TCP_KEEPCNT, 3))

    # `verify` aussi sur le Client : les montages proxy que httpx crée depuis HTTPS_PROXY
    # prennent le verify du Client, pas celui de la transport explicite.
    http_client = _httpx.Client(
        timeout=_httpx.Timeout(connect=10, read=60, write=30, pool=10),
        verify=verify,
        transport=_httpx.HTTPTransport(verify=verify, socket_options=keepalive_opts),
    )
    # max_retries=0 : les relances du SDK absorbaient en silence 429, 529 et 5xx avant
    # _create_anthropic_stream_with_retry, qui journalise chaque tentative, attend
    # progressivement et respecte Retry-After. Ce client n'a pas d'autre appelant.
    # default_headers : en-têtes X-Demo-* du proxy LLM du portail (vide ailleurs).
    extra = {"default_headers": dict(default_headers)} if default_headers else {}
    try:
        return _ant.Anthropic(
            api_key=api_key or None,
            base_url=base_url or None,
            http_client=http_client,
            max_retries=0,
            **extra,
        )
    except TypeError:
        # The SDK refused our transport (e.g. httpx/httpx2 mismatch we could not
        # resolve). Losing TCP keep-alive is far better than a client that cannot be
        # built at all, which breaks every single turn.
        return _ant.Anthropic(
            api_key=api_key or None,
            base_url=base_url or None,
            max_retries=0,
            **extra,
        )
