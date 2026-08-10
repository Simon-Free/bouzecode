# [desc] HookContext: the STABLE API passed to hooks (fields + helper methods) so hooks never import bouzecode internals. [/desc]
"""The context object handed to every hook.

`HookContext` is the *stable contract* between the core and any hook (builtin OR
plugin), the same philosophy as ``TOOL_DEFS`` being pure dicts: a hook reads the
declared fields and calls the declared helper methods, and NEVER imports
``services/work/*`` or ``web/runner`` directly. Internally the helpers talk to
the long-lived server over HTTP (the agent runs as a subprocess of that server),
but that plumbing is invisible to the hook.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DEFAULT_BASE_URL = "http://127.0.0.1:5056"


def _http(method: str, url: str, body: dict | None, timeout: int = 60) -> dict:
    """Appel au serveur LOCAL via `core.local_http` : opener sans proxy, donc insensible à
    un `NO_PROXY` absent ou incomplet dans l'environnement hérité par l'agent. Avec
    `urlopen`, un hook de complétion pouvait voir son POST partir dans le proxy
    d'entreprise et revenir en 407 (panne du 2026-07-28)."""
    from ...core.local_http import local_json
    return local_json(method, url, body, timeout=timeout)


@dataclass
class HookContext:
    """Stable API surface for hooks. Fields are read-only inputs; the helper
    methods are the ONLY sanctioned way for a hook to act on the outside world."""

    event: str = ""
    self_id: str = ""          # this agent's id ("" when ungoverned / CLI)
    profile: str = ""          # resolved profile name of this agent
    run_kind: str = "work"     # BOUZECODE_RUN_KIND (work|validate|…)
    final_text: str = ""       # FinalAnswer answer, else last assistant text
    close_reason: str = ""     # graceful close reason (final_answer|text_no_tools)
    config: dict = field(default_factory=dict)

    # ── stable helper API ────────────────────────────────────────────────────
    def base_url(self) -> str:
        return os.environ.get("BOUZECODE_WEB_BASE_URL", _DEFAULT_BASE_URL)

    def http_post(self, path: str, body: dict, timeout: int = 60) -> dict:
        return _http("POST", self.base_url() + path, body, timeout=timeout)

    def http_get(self, path: str) -> dict:
        return _http("GET", self.base_url() + path, None)

    def ticket(self) -> dict:
        """Current ticket (with runs) this agent belongs to, or {} if unknown."""
        slug = os.environ.get("BOUZECODE_TICKET_SLUG", "")
        tid = os.environ.get("BOUZECODE_TICKET_ID", "")
        if not (slug and tid):
            return {}
        return self.http_get(f"/api/tickets/{slug}/{tid}")

    def continue_agent(self, agent_id: str, message: str) -> dict:
        """Resume an existing agent (same session/context) with a follow-up."""
        return self.http_post(f"/api/agents/{agent_id}/continue", {"text": message})

    def spawn_agent(self, prompt: str, typology: str = "",
                    env: dict | None = None) -> str:
        """Dispatch a new governed agent; returns the created ticket id."""
        body: dict[str, Any] = {"prompt": prompt, "typology": typology}
        if env:
            body["env"] = env
        return self.http_post("/api/dispatch", body).get("ticket_id", "")


def _extract_final_text(state) -> str:
    """FinalAnswer answer if the last assistant turn carries one, else its text."""
    for msg in reversed(getattr(state, "messages", []) or []):
        if msg.get("role") != "assistant":
            continue
        for call in msg.get("tool_calls") or []:
            if call.get("name") == "FinalAnswer":
                answer = str((call.get("input") or {}).get("answer", "")).strip()
                if answer:
                    return answer
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def completion_context(state, config: dict, close_reason: str) -> HookContext:
    """Build the HookContext for an `on_completion` fire (graceful close only)."""
    self_id = ""
    ipc = os.environ.get("BOUZECODE_WEB_IPC_DIR")
    if ipc:
        self_id = Path(ipc).stem  # ".../<agent_id>.ipc" -> "<agent_id>"
    return HookContext(
        event="on_completion",
        self_id=self_id,
        profile=str(config.get("_task_classification_result", "") or ""),
        run_kind=os.environ.get("BOUZECODE_RUN_KIND", "work"),
        final_text=_extract_final_text(state),
        close_reason=close_reason,
        config=config,
    )
