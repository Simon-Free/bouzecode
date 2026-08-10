# [desc] HTTP transport for OpenRouter: outbound-proxy session + SSE line iteration with raw dump. [/desc]
from __future__ import annotations
import json
import os
from urllib.parse import quote, urlsplit, urlunsplit
from typing import Generator

ENV_PROXY_URL = "BOUZECODE_PROXY_URL"
ENV_PROXY_USER = "BOUZECODE_PROXY_USER"
ENV_PROXY_PASSWORD = "BOUZECODE_PROXY_PASSWORD"


def _proxy_url() -> str:
    """The outbound proxy URL, with credentials injected when supplied.

    BOUZECODE_PROXY_USER / BOUZECODE_PROXY_PASSWORD are URL-encoded into the
    userinfo part, which is how requests passes proxy Basic credentials."""
    url = os.environ.get(ENV_PROXY_URL, "")
    user, password = os.environ.get(ENV_PROXY_USER), os.environ.get(ENV_PROXY_PASSWORD)
    if not url or not user or not password:
        return url
    parts = urlsplit(url)
    userinfo = f"{quote(user, safe='')}:{quote(password, safe='')}"
    return urlunsplit(parts._replace(netloc=f"{userinfo}@{parts.netloc}"))


def build_session():
    """A requests session for EXTERNAL endpoints (OpenRouter).

    Set BOUZECODE_PROXY_URL to route through an outbound proxy (plus
    BOUZECODE_PROXY_USER / BOUZECODE_PROXY_PASSWORD when it authenticates).
    Unset, the session falls back to the standard HTTP_PROXY/HTTPS_PROXY env
    vars that requests already honours."""
    import requests
    session = requests.Session()
    proxy = _proxy_url()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    return session


def build_plain_session():
    """A bare requests session with NO proxy — for endpoints reached directly
    (a self-hosted gateway on the local network), which must not traverse the
    outbound proxy configured for OpenRouter."""
    import requests
    session = requests.Session()
    session.trust_env = False  # ignore HTTP_PROXY/HTTPS_PROXY for this session
    return session


def iter_sse(resp) -> Generator:
    """Yield parsed JSON chunks from an OpenAI-compatible SSE stream.

    Set BOUZECODE_DUMP_SSE=<path> to append every raw SSE line to a file
    (diagnostic: see exactly what the provider sent, including error chunks
    and finish_reason that the loop might otherwise swallow)."""
    dump_path = os.environ.get("BOUZECODE_DUMP_SSE")
    dump = open(dump_path, "a", encoding="utf-8") if dump_path else None
    if dump:
        dump.write("\n=== SSE stream start ===\n")
    try:
        for raw in resp.iter_lines(decode_unicode=True):
            if dump and raw:
                dump.write(raw + "\n")
                dump.flush()
            if not raw or not raw.startswith("data: "):
                continue
            payload = raw[6:]
            if payload.strip() == "[DONE]":
                return
            try:
                yield json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                continue
    finally:
        if dump:
            dump.write("=== SSE stream end ===\n")
            dump.close()
