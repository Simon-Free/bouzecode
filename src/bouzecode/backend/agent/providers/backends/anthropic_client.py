# [desc] Builds the Anthropic SDK client with a keep-alive httpx transport tuned for gateways. [/desc]
from __future__ import annotations
import os


def build_anthropic_client(api_key: str, base_url: str | None):
    """Anthropic SDK client over an httpx transport with TCP keep-alive.

    A corporate LLM gateway in front of the API can silently drop idle connections
    mid-stream; keep-alive probes surface the drop as a real error the retry loop
    can act on instead of an infinite stall.
    """
    import anthropic as _ant
    import httpx as _httpx
    import socket as _socket

    skip_ssl = os.environ.get("BOUZECODE_SSL_NO_VERIFY") == "1"
    keepalive_opts = [(_socket.SOL_SOCKET, _socket.SO_KEEPALIVE, 1)]
    # Linux: TCP_KEEPIDLE. macOS: TCP_KEEPALIVE. Windows: neither.
    keepidle = getattr(_socket, "TCP_KEEPIDLE", getattr(_socket, "TCP_KEEPALIVE", None))
    if keepidle is not None:
        keepalive_opts.append((_socket.IPPROTO_TCP, keepidle, 30))
    if hasattr(_socket, "TCP_KEEPINTVL"):
        keepalive_opts.append((_socket.IPPROTO_TCP, _socket.TCP_KEEPINTVL, 10))
    if hasattr(_socket, "TCP_KEEPCNT"):
        keepalive_opts.append((_socket.IPPROTO_TCP, _socket.TCP_KEEPCNT, 3))

    http_client = _httpx.Client(
        timeout=_httpx.Timeout(connect=10, read=60, write=30, pool=10),
        transport=_httpx.HTTPTransport(verify=not skip_ssl, socket_options=keepalive_opts),
    )
    return _ant.Anthropic(
        api_key=api_key or None,
        base_url=base_url or None,
        http_client=http_client,
        max_retries=3,
    )
