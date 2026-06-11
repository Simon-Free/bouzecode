# [desc] Retry policy for OpenRouter requests: backoff on 429/5xx, one retry on 400 (provider rotation). [/desc]
from __future__ import annotations
import time

# 429s come from upstream provider rate limits and clear once OpenRouter rotates
# providers; a 400 has been observed from a single bad fallback provider
# (AtlasCloud "invalid request params") right after a 429 — one rotation retry
# usually lands on a healthy provider. Total worst-case wait: ~60s.
BACKOFFS_S = (2.0, 4.0, 8.0, 16.0, 30.0)


def post_with_retry(post_once, sleep=time.sleep):
    """Call post_once() -> requests.Response until one is OK.

    Retries 429/5xx through BACKOFFS_S and 400 once; any other error status —
    or exhausted budget — raises with the response body in the message."""
    backoffs = list(BACKOFFS_S)
    retried_400 = False
    while True:
        resp = post_once()
        if resp.ok:
            return resp
        if resp.status_code == 400 and not retried_400:
            retried_400 = True
            sleep(2.0)
            continue
        if (resp.status_code == 429 or resp.status_code >= 500) and backoffs:
            sleep(backoffs.pop(0))
            continue
        raise RuntimeError(
            f"OpenRouter request failed: HTTP {resp.status_code}\n{resp.text[:800]}"
        )
