# [desc] HTTP transport for OpenRouter: NTLM-proxy session + SSE line iteration with raw dump. [/desc]
from __future__ import annotations
import hashlib
import json
import os
from typing import Generator


def _ensure_md4_available() -> None:
    """OpenSSL 3 disables MD4 (which NTLM needs); back hashlib with passlib's."""
    try:
        hashlib.new("md4")
    except ValueError:
        from passlib.utils.md4 import md4
        _orig = hashlib.new

        def _patched(name, data=b"", **kw):
            if name.lower() == "md4":
                h = md4()
                h.update(data)
                return h
            return _orig(name, data, **kw)

        hashlib.new = _patched


def build_session():
    """A requests session authenticating the SNCF NTLM proxy when one is set.

    Discriminates on the environment: NTLM proxy when SNCF_HTTPS_PROXY + CP/PW
    are present (the SNCF socle case), otherwise a plain session for direct
    internet access. Mirrors connectors/cayzn_connector/ntlm_session.py."""
    import requests
    session = requests.Session()
    proxy = os.environ.get("SNCF_HTTPS_PROXY")
    cp, pw = os.environ.get("CP"), os.environ.get("PW")
    if proxy and cp and pw:
        _ensure_md4_available()
        from requests_ntlm2 import HttpNtlmAdapter, NtlmCompatibility
        user = f"COMMUN\\{cp}"
        for scheme in ("https://", "http://"):
            session.mount(scheme, HttpNtlmAdapter(
                user, pw, ntlm_compatibility=NtlmCompatibility.NTLMv2_DEFAULT))
        session.proxies = {
            "http": os.environ.get("SNCF_HTTP_PROXY") or proxy, "https": proxy,
        }
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
