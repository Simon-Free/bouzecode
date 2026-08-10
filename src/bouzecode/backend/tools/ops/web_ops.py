# [desc] Web fetch/search ops with httpx primary path and curl.exe fallback for Windows-integrated corporate proxy auth. [/desc]
"""Web fetch and search operations.

Corporate-proxy aware: tries httpx first (works in dev / no auth), then falls
back to the native curl.exe, which handles Windows-integrated proxy auth via
`--proxy-anyauth -U :` — no password to store, no extra pip dependency.
"""
import json
import os
import random
import re
import shutil
import subprocess
import time
from urllib.parse import urlencode

_DEFAULT_TIMEOUT = 30

# DuckDuckGo has no documented quota, but its html/lite endpoint serves an
# anti-bot "anomaly" page (0 results) when hit too fast or from a shared/hot IP
# (typical behind a corporate proxy). We therefore serialise WebSearch (see
# concurrent_safe=False in registration.py) AND throttle at module level: keep a
# minimum interval between two searches and retry once, after a longer pause, if
# an anomaly page comes back.
_SEARCH_MIN_INTERVAL = 2.0    # seconds between two consecutive searches
_SEARCH_MAX_RETRIES = 6       # extra attempts after the first (backoff 1,2,4,8,16,32s)
_SEARCH_BACKOFF_BASE = 1.0    # first backoff = BASE * 2**0 (+ jitter)
_SEARCH_BACKOFF_CAP = 32.0    # per-attempt backoff ceiling
_last_search_ts = 0.0


def _search_throttle() -> None:
    """Sleep just enough to keep _SEARCH_MIN_INTERVAL between two searches."""
    global _last_search_ts
    now = time.monotonic()
    wait = _SEARCH_MIN_INTERVAL - (now - _last_search_ts)
    if wait > 0:
        time.sleep(wait)
    _last_search_ts = time.monotonic()


def _is_anomaly(raw: str) -> bool:
    """True if DDG returned its anti-bot page instead of real results."""
    low = raw.lower()
    return ("anomaly" in low or "error-lite@duckduckgo" in low) and \
        'class="result__title"' not in raw


def _http_get(url: str, params: dict = None, headers: dict = None,
              timeout: int = _DEFAULT_TIMEOUT) -> str:
    """Return the body text of a GET request.

    Primary path: httpx (honours HTTP(S)_PROXY via trust_env). If that raises
    for any reason (typically HTTP 407 behind an authenticated corporate proxy
    that httpx cannot traverse), fall back to the system curl.exe which can do
    Windows-integrated proxy authentication.
    """
    headers = headers or {}
    # 1) httpx attempt (fast path, works in dev and unauthenticated proxies).
    try:
        import httpx
        r = httpx.get(url, params=params, headers=headers,
                      timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except ImportError:
        # httpx missing: fall through to curl if available, else surface error.
        pass
    except Exception:
        # Any httpx failure (incl. 407 proxy auth) -> try curl fallback below.
        pass

    # 2) curl.exe fallback (native on Windows 10/11; --proxy-anyauth -U : uses
    #    the current user's Windows credentials, no password prompt).
    curl = shutil.which("curl") or shutil.which("curl.exe")
    if not curl:
        raise RuntimeError("httpx failed and curl.exe not found for proxy fallback")

    full_url = url
    if params:
        sep = "&" if "?" in url else "?"
        full_url = f"{url}{sep}{urlencode(params)}"

    cmd = [curl, "-sSL", "--max-time", str(timeout),
           "--proxy-anyauth", "-U", ":", full_url]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]

    proc = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"curl fallback failed (exit {proc.returncode}): {err}")
    return proc.stdout.decode("utf-8", errors="replace")


def _http_post(url: str, json_body: dict, headers: dict = None,
               timeout: int = _DEFAULT_TIMEOUT) -> str:
    """Return the body text of a JSON POST request.

    Primary path: httpx (honours HTTP(S)_PROXY via trust_env). On any failure
    (typically HTTP 407 behind an authenticated corporate proxy), fall back to
    the system curl.exe which can do Windows-integrated proxy authentication.
    """
    headers = headers or {}
    body = json.dumps(json_body)
    # 1) httpx attempt.
    try:
        import httpx
        r = httpx.post(url, content=body,
                       headers={**headers, "content-type": "application/json"},
                       timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except ImportError:
        pass
    except Exception:
        pass

    # 2) curl.exe fallback (--proxy-anyauth -U : = Windows-integrated proxy auth).
    curl = shutil.which("curl") or shutil.which("curl.exe")
    if not curl:
        raise RuntimeError("httpx failed and curl.exe not found for proxy fallback")
    cmd = [curl, "-sS", "-X", "POST", "--max-time", str(timeout),
           "--proxy-anyauth", "-U", ":",
           "-H", "content-type: application/json"]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    cmd += ["--data", body, url]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"curl fallback failed (exit {proc.returncode}): {err}")
    return proc.stdout.decode("utf-8", errors="replace")


def _exa_search(query: str, api_key: str) -> str:
    """Search via the Exa API (https://api.exa.ai/search).

    Raises on network/JSON/API error so the caller can fall back to DDG.
    """
    raw = _http_post(
        "https://api.exa.ai/search",
        json_body={
            "query": query,
            "numResults": 8,
            "type": "auto",
            "contents": {"text": {"maxCharacters": 400}},
        },
        headers={"x-api-key": api_key},
    )
    data = json.loads(raw)
    results = data.get("results")
    if results is None:
        # Surface an API-level error (e.g. bad key / quota) to trigger fallback.
        raise RuntimeError(f"Exa API error: {raw[:300]}")
    out = []
    for r in results[:8]:
        title = (r.get("title") or "").strip()
        url = (r.get("url") or "").strip()
        text = (r.get("text") or "").strip().replace("\n", " ")
        out.append(f"**{title}**\n{url}\n{text[:400]}")
    return "\n\n".join(out) if out else "No results found"


def _webfetch(url: str, prompt: str = None) -> str:
    try:
        raw = _http_get(url, headers={"User-Agent": "NanoClaude/1.0"})
    except Exception as e:
        return f"Error: {e}"
    # Heuristic: treat as HTML if it looks like markup.
    if "<html" in raw.lower() or "<body" in raw.lower() or "<!doctype" in raw.lower():
        text = re.sub(r"<script[^>]*>.*?</script>", "", raw,
                      flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text,
                      flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
    else:
        text = raw
    return text[:25000]


def _websearch(query: str) -> str:
    # Preferred backend: Exa API when EXA_KEY is set (clean API, avoids the DDG
    # anti-bot / corporate-proxy-IP blocking entirely). Fall back to DuckDuckGo
    # scraping on any Exa failure so search keeps working without a key.
    _exa_key = os.getenv("EXA_KEY")
    if _exa_key:
        try:
            return _exa_search(query, _exa_key)
        except Exception:
            pass  # fall through to DuckDuckGo scraping fallback

    def _fetch() -> str:
        return _http_get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (compatible)"},
        )

    # Exponential backoff: try, then retry with delays 1,2,4,8s (+ jitter),
    # capped at _SEARCH_BACKOFF_CAP, on either an anomaly page or a network
    # error. The module-level throttle already spaced us from the previous
    # search; each retry adds its own growing pause on top.
    _search_throttle()
    raw = None
    last_err = None
    for attempt in range(_SEARCH_MAX_RETRIES + 1):
        if attempt > 0:
            backoff = min(_SEARCH_BACKOFF_BASE * (2 ** (attempt - 1)),
                          _SEARCH_BACKOFF_CAP)
            time.sleep(backoff + random.uniform(0.0, 0.5))
        try:
            candidate = _fetch()
        except Exception as e:
            last_err = e
            continue
        if not _is_anomaly(candidate):
            raw = candidate
            break
        last_err = None  # anomaly, not an exception
    if raw is None:
        if last_err is not None:
            return f"Error: {last_err}"
        return ("No results found (DuckDuckGo rate-limit / anti-bot page "
                f"returned after {_SEARCH_MAX_RETRIES + 1} attempts; "
                "try again in a few seconds)")
    titles = re.findall(
        r'class="result__title"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        raw, re.DOTALL)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</div>', raw, re.DOTALL)
    results = []
    for i, (link, title) in enumerate(titles[:8]):
        t = re.sub(r"<[^>]+>", "", title).strip()
        s = re.sub(r"<[^>]+>", "", snippets[i]).strip() if i < len(snippets) else ""
        results.append(f"**{t}**\n{link}\n{s}")
    return "\n\n".join(results) if results else "No results found"
