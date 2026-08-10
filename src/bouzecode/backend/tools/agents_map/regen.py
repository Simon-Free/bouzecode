# [desc] Runs the single regeneration LLM call and renders the map file (frontmatter + body). [/desc]
from __future__ import annotations

import os
from pathlib import Path

from .inputs import (
    build_agents_message,
    build_symbols_message,
    legal_identifiers,
    symbol_names,
)
from .manifest import folder_manifest, iter_code_folders, render_frontmatter, tree_sha
from .progress import progress_reporter
from .prompts import AGENTS_SYSTEM_PROMPT, CONTRACT_VERSION, SYMBOLS_SYSTEM_PROMPT

DEFAULT_MODEL = "claude-opus-4-8"

def model_name() -> str:
    return os.environ.get("BOUZECODE_AGENTS_MAP_MODEL", DEFAULT_MODEL)


def compose(body: str, manifest: dict) -> str:
    """Frontmatter + body, deterministic, exactly one trailing newline."""
    return render_frontmatter(manifest) + "\n" + body.strip() + "\n"


def symbols_manifest(folder: Path, model: str) -> dict:
    return {"symbols_map": 1, "model": model, "contract": CONTRACT_VERSION,
            "files": folder_manifest(folder)}


def agents_manifest(root: Path, model: str) -> dict:
    return {"agents_map": 1, "model": model, "contract": CONTRACT_VERSION,
            "tree_sha256": tree_sha(root), "folders": len(list(iter_code_folders(root)))}


def strip_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


_RETRY_HEADER = (
    "\n\n## Your previous attempt broke the contract — fix exactly these and nothing else\n"
    "These were checked against the code's AST, so they are facts, not opinions.\n"
)


def call_llm(client, system: str, user: str, model: str, feedback: str = "",
             max_tokens: int = 8192, on_delta=None) -> str:
    if feedback:
        user += _RETRY_HEADER + feedback
    # STREAMING quand un `on_delta` est fourni ET que le client sait streamer (le vrai
    # SDK Anthropic expose `messages.stream`). On accumule le texte token par token et
    # on rend compte de la progression réelle à chaque delta. Les fakes de test n'ont
    # que `create` → on retombe sur le chemin bloquant, inchangé, sans les casser.
    if on_delta is not None and hasattr(client.messages, "stream"):
        acc = ""
        with client.messages.stream(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            for text in stream.text_stream:
                acc += text
                on_delta(acc)
        return strip_fence(acc)
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return strip_fence("".join(b.text for b in resp.content if b.type == "text"))


def generate_symbols(folder: Path, root: Path, client, model: str, feedback: str = "") -> str:
    with progress_reporter(f"SymbolMap: {folder.name}") as report:
        return call_llm(
            client, SYMBOLS_SYSTEM_PROMPT, build_symbols_message(folder, root), model,
            feedback, on_delta=report)


# The root map is one row per code folder and grows with the repository; 8 192 tokens
# cut this repo's first real generation at 103 of 137 rows, mid-row. The ceiling has to
# scale with the tree, not with a folder.
AGENTS_MAX_TOKENS = 32000


def generate_agents(
    root: Path, current: str, diff: list[str], client, model: str, feedback: str = "",
) -> str:
    with progress_reporter(f"AgentsMap: {root.name}") as report:
        return call_llm(
            client, AGENTS_SYSTEM_PROMPT, build_agents_message(root, current, diff), model,
            feedback, max_tokens=AGENTS_MAX_TOKENS, on_delta=report)
