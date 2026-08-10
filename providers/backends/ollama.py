# [desc] Streams chat completions from an Ollama API with tool-calling and thinking support. [/desc]
from __future__ import annotations
import json
import urllib.request
import urllib.error
from typing import Generator

from providers.types import StreamStarted, TextChunk, ThinkingChunk, AssistantTurn
from providers.conversion import tools_to_openai, messages_to_openai


def stream_ollama(
    base_url: str,
    model: str,
    system: str,
    messages: list,
    tool_schemas: list,
    config: dict,
) -> Generator:
    oai_messages = [{"role": "system", "content": system}] + messages_to_openai(messages, ollama_native_images=True)

    for m in oai_messages:
        if m.get("content") is None:
            m["content"] = ""
        if "tool_calls" in m and m["tool_calls"]:
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                if isinstance(fn.get("arguments"), str):
                    try:
                        fn["arguments"] = json.loads(fn["arguments"])
                    except Exception:
                        pass

    payload = {
        "model": model,
        "messages": oai_messages,
        "stream": True,
        "options": {
            "num_ctx": config.get("context_limit", 128000)
        }
    }

    if tool_schemas and not config.get("no_tools"):
        payload["tools"] = tools_to_openai(tool_schemas)

    def _make_request(p):
        return urllib.request.Request(
            f"{base_url.rstrip('/')}/api/chat",
            data=json.dumps(p).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

    req = _make_request(payload)

    text = ""
    tool_buf: dict = {}
    in_tok = out_tok = 0
    _stream_started = False

    try:
        resp_cm = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        if e.code == 500 and "tools" in payload:
            print(
                f"\n\033[33m[warn] {model} returned HTTP 500 (likely no tool-calling support)."
                " Retrying without tools.\033[0m"
            )
            payload.pop("tools", None)
            req = _make_request(payload)
            resp_cm = urllib.request.urlopen(req)
        else:
            raise

    with resp_cm as resp:
        for line in resp:
            if not line.strip(): continue
            try:
                data = json.loads(line)
            except Exception:
                continue

            msg = data.get("message", {})

            if not _stream_started and msg:
                _stream_started = True
                yield StreamStarted()

            if "thinking" in msg and msg["thinking"]:
                yield ThinkingChunk(msg["thinking"])

            if "content" in msg and msg["content"]:
                text += msg["content"]
                yield TextChunk(msg["content"])

            for tc in msg.get("tool_calls", []):
                fn = tc.get("function", {})
                idx = len(tool_buf)
                tool_buf[idx] = {
                    "id": "call_ollama" + str(idx),
                    "name": fn.get("name", ""),
                    "args": json.dumps(fn.get("arguments", {})),
                    "input": fn.get("arguments", {})
                }

            if data.get("done"):
                in_tok = data.get("prompt_eval_count", 0) or 0
                out_tok = data.get("eval_count", 0) or 0

    tool_calls = []
    for idx in sorted(tool_buf):
        v = tool_buf[idx]
        tool_calls.append({"id": v["id"], "name": v["name"], "input": v["input"]})

    yield AssistantTurn(text, tool_calls, in_tok, out_tok)


def list_ollama_models(base_url: str) -> list[str]:
    try:
        url = f"{base_url.rstrip('/')}/api/tags"
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []
