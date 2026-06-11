# [desc] Classifies user prompts into title/project/typology via a lightweight LLM call with tolerant parsing. [/desc]
"""Classify a user prompt into title / project / typology with one LLM call."""
from __future__ import annotations

import logging
from typing import Any, Callable, Generator

logger = logging.getLogger(__name__)

_MAX_USER_CHARS = 2000
_MAX_TOKENS = 200
_CLASSIFY_MODEL = "deepseek-v4-flash"

_SYSTEM_PROMPT = """\
Tu reçois un prompt utilisateur et des listes de projets et typologies.
Réponds EXACTEMENT en 3 lignes, sans autre texte :
TITLE: <titre court, max 80 car>
PROJECT: <slug du projet le plus pertinent parmi la liste, ou NONE>
TYPOLOGY: <nom de la typologie la plus pertinente parmi la liste, ou default>
"""

# Module-level patchable stream function (for testing without mock.patch)
dispatch_stream: Callable | None = None


def _get_dispatch_stream():
    """Lazy import of dispatch.stream — separate function for easy patching."""
    from ...backend.agent.providers.backends.dispatch import stream
    return stream


def _collect_stream_text(gen: Generator) -> str:
    """Consume stream generator and collect text chunks."""
    parts: list[str] = []
    for event in gen:
        if hasattr(event, "text"):
            parts.append(event.text)
        elif isinstance(event, str):
            parts.append(event)
    return "".join(parts)


def _parse_classify_response(
    text: str,
    projects: list[dict[str, Any]],
    typologies: list[dict[str, Any]],
) -> dict[str, Any]:
    """Parse LLM response. Tolerant matching with validation against known lists."""
    valid_slugs = {p.get("slug", p.get("name", "")) for p in projects}
    valid_typos = {t["name"] for t in typologies}

    title = ""
    project_slug: str | None = None
    typology = "default"

    for line in text.splitlines():
        lower = line.lower().strip()
        if lower.startswith("title:"):
            title = line.split(":", 1)[1].strip()[:80]
        elif lower.startswith("project:"):
            val = line.split(":", 1)[1].strip()
            if val.lower() != "none" and val in valid_slugs:
                project_slug = val
        elif lower.startswith("typology:") or lower.startswith("typologie:"):
            val = line.split(":", 1)[1].strip()
            if val in valid_typos:
                typology = val

    return {"title": title, "project_slug": project_slug, "typology": typology}


def _fallback(prompt: str) -> dict[str, Any]:
    """Safe fallback when classification fails."""
    first_line = prompt.split("\n")[0][:80].strip()
    return {"title": first_line, "project_slug": None, "typology": "default"}


def classify_prompt(
    prompt: str,
    projects: list[dict[str, Any]],
    typologies: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify prompt into title/project/typology via lightweight LLM call.

    Falls back gracefully on any error.
    """
    global dispatch_stream

    if not prompt.strip():
        return _fallback(prompt)

    truncated = prompt[:_MAX_USER_CHARS]
    project_slugs = [p.get("slug", p.get("name", "")) for p in projects]
    typology_names = [t["name"] for t in typologies]

    user_content = (
        f"Projets disponibles: {', '.join(project_slugs)}\n"
        f"Typologies disponibles: {', '.join(typology_names)}\n\n"
        f"Prompt utilisateur:\n{truncated}"
    )
    messages = [{"role": "user", "content": user_content}]

    try:
        stream_fn = dispatch_stream or _get_dispatch_stream()
        response_text = _collect_stream_text(
            stream_fn(
                model=_CLASSIFY_MODEL,
                system=_SYSTEM_PROMPT,
                messages=messages,
                tool_schemas=[],
                config={
                    "max_tokens": _MAX_TOKENS,
                    "thinking_mode": "off",
                    "task_classification": False,
                    "_depth": 1,
                    "_context_state": None,
                },
            )
        )
        result = _parse_classify_response(response_text, projects, typologies)
        # If title is empty after parsing, use fallback title
        if not result["title"]:
            result["title"] = prompt.split("\n")[0][:80].strip()
        return result
    except Exception as exc:
        logger.warning("classify_prompt: failed (%s), using fallback", exc)
        return _fallback(prompt)
