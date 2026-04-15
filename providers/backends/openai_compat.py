# [desc] Streams chat completions from OpenAI-compatible APIs with tool-call support. [/desc]
from __future__ import annotations
import json
from typing import Generator

from providers.types import (
    sanitize_tool_name, StreamStarted, TextChunk, AssistantTurn,
)
from providers.conversion import tools_to_openai, messages_to_openai
from providers.registry import detect_provider, PROVIDERS


def stream_openai_compat(
    api_key: str,
    base_url: str,
    model: str,
    system: str,
    messages: list,
    tool_schemas: list,
    config: dict,
) -> Generator:
    from openai import OpenAI
    client = OpenAI(api_key=api_key or "dummy", base_url=base_url)

    oai_messages = [{"role": "system", "content": system}] + messages_to_openai(messages)

    kwargs: dict = {
        "model":    model,
        "messages": oai_messages,
        "stream":   True,
    }

    _is_local_ollama = "11434" in base_url
    _is_lmstudio = "1234" in base_url and ("lmstudio" in base_url or "localhost" in base_url or "127.0.0.1" in base_url)
    if _is_local_ollama or _is_lmstudio:
        prov = detect_provider(model)
        ctx_limit = PROVIDERS.get(prov if prov in ("ollama", "lmstudio") else "ollama", {}).get("context_limit", 128000)
        kwargs["extra_body"] = {"options": {"num_ctx": ctx_limit}}

    if tool_schemas and not config.get("no_tools"):
        kwargs["tools"] = tools_to_openai(tool_schemas)
        if not config.get("disable_tool_choice"):
            kwargs["tool_choice"] = "auto"
    if config.get("max_tokens"):
        prov_cap = PROVIDERS.get(detect_provider(model), {}).get("max_completion_tokens")
        mt = config["max_tokens"]
        kwargs["max_tokens"] = min(mt, prov_cap) if prov_cap else mt

    text          = ""
    tool_buf: dict = {}
    in_tok = out_tok = 0
    _stream_started = False

    stream = client.chat.completions.create(**kwargs)
    for chunk in stream:
        if not chunk.choices:
            if hasattr(chunk, "usage") and chunk.usage:
                in_tok  = chunk.usage.prompt_tokens
                out_tok = chunk.usage.completion_tokens
            continue

        if not _stream_started:
            _stream_started = True
            yield StreamStarted()

        choice = chunk.choices[0]
        delta  = choice.delta

        if delta.content:
            text += delta.content
            yield TextChunk(delta.content)

        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tool_buf:
                    tool_buf[idx] = {"id": "", "name": "", "args": "", "extra_content": None}
                if tc.id:
                    tool_buf[idx]["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        tool_buf[idx]["name"] += tc.function.name
                    if tc.function.arguments:
                        tool_buf[idx]["args"] += tc.function.arguments
                extra = getattr(tc, "extra_content", None)
                if extra:
                    tool_buf[idx]["extra_content"] = extra

        if hasattr(chunk, "usage") and chunk.usage:
            in_tok  = chunk.usage.prompt_tokens  or in_tok
            out_tok = chunk.usage.completion_tokens or out_tok

    tool_calls = []
    for idx in sorted(tool_buf):
        v = tool_buf[idx]
        try:
            inp = json.loads(v["args"]) if v["args"] else {}
        except json.JSONDecodeError:
            inp = {"_raw": v["args"]}
        safe_name, corrupted = sanitize_tool_name(v["name"])
        if corrupted is not None:
            inp["_corrupted_name"] = corrupted
        tc_entry = {"id": v["id"] or f"call_{idx}", "name": safe_name, "input": inp}
        if v.get("extra_content"):
            tc_entry["extra_content"] = v["extra_content"]
        tool_calls.append(tc_entry)

    yield AssistantTurn(text, tool_calls, in_tok, out_tok)
