# [desc] Routes LLM streaming requests to the appropriate provider backend based on model/provider type. [/desc]
from __future__ import annotations
import os
from typing import Generator

from providers.registry import detect_provider, bare_model, get_api_key, PROVIDERS
from providers.backends.anthropic_stream import stream_anthropic
from providers.backends.openai_compat import stream_openai_compat
from providers.backends.ollama import stream_ollama


def stream(
    model: str,
    system: str,
    messages: list,
    tool_schemas: list,
    config: dict,
) -> Generator:
    provider_name = detect_provider(model)
    model_name    = bare_model(model)
    prov          = PROVIDERS.get(provider_name, PROVIDERS["openai"])
    api_key       = get_api_key(provider_name, config)

    if prov["type"] == "anthropic":
        # XML tool protocol: describe tools in the system prompt so the LLM emits
        # them as XML text. Native tool_use SSE blocks are bypassed (proxy-mangled).
        from xml_tool_protocol import build_tool_docs
        system = (system or "") + "\n\n" + build_tool_docs(tool_schemas or [])
        base_url = prov.get("base_url")
        yield from stream_anthropic(api_key, model_name, system, messages, tool_schemas, config, base_url=base_url)
    elif prov["type"] == "ollama":
        base_url = prov.get("base_url", "http://localhost:11434")
        yield from stream_ollama(base_url, model_name, system, messages, tool_schemas, config)
    else:
        if provider_name == "custom":
            base_url = (config.get("custom_base_url")
                        or os.environ.get("CUSTOM_BASE_URL", ""))
            if not base_url:
                raise ValueError(
                    "custom provider requires a base_url. "
                    "Set CUSTOM_BASE_URL env var or run: /config custom_base_url=http://..."
                )
        else:
            base_url = prov.get("base_url", "https://api.openai.com/v1")
        yield from stream_openai_compat(
            api_key, base_url, model_name, system, messages, tool_schemas, config
        )
