# [desc] Keyword search across agent conversations, matching user messages and FinalAnswer reports. [/desc]
"""Recherche par mot-clé dans les conversations d'agents.

Fouille les contenus SIGNIFIANTS d'une session : messages ``role=="user"``
(content str) et le RAPPORT FinalAnswer du modèle (via ``extract_final_answer``).
Le thinking et les tool_results bruts sont ignorés.
"""
from __future__ import annotations

import json
from pathlib import Path

from .work import projects, tickets
from .work.tickets import extract_final_answer

SNIPPET_RADIUS = 80
MAX_MATCHES_PER_AGENT = 3
MAX_AGENTS = 50


def search_agents(query: str, scope: str = "open") -> list[dict]:
    """Cherche ``query`` (AND multi-mots, casefold) dans les conversations.

    ``scope`` : ``"open"`` (défaut) = agents des tickets non archivés ;
    ``"all"`` = toutes les sessions présentes sur disque.
    Renvoie une liste d'agents (max 50) avec leurs extraits (max 3).
    """
    words = [w for w in query.casefold().split() if w]
    if not words:
        return []

    index = _ticket_index()
    sessions = _session_paths(scope, index)

    first = words[0].encode("utf-8").lower()
    results: list[dict] = []
    for agent_id, path in sessions:
        if len(results) >= MAX_AGENTS:
            break
        matches = _search_session(path, words, first)
        if not matches:
            continue
        slug, ticket_id, title = index.get(agent_id, (None, None, None))
        results.append({
            "agent_id": agent_id,
            "key": f"agent/{agent_id}",
            "ticket_slug": slug,
            "ticket_id": ticket_id,
            "ticket_title": title,
            "matches": matches,
        })
    return results


def _ticket_index() -> dict[str, tuple[str, str, str]]:
    """Index ``{agent_id: (slug, ticket_id, title)}`` des tickets non archivés.

    Lecture store brute (``list_tickets`` sans refresh) — jamais de refresh
    dans le chemin de recherche.
    """
    index: dict[str, tuple[str, str, str]] = {}
    for project in projects.list_projects():
        slug = project.get("slug")
        if not slug:
            continue
        for ticket in tickets.list_tickets(slug):
            for run in ticket.get("runs") or []:
                agent_id = run.get("agent_id")
                if agent_id:
                    index[agent_id] = (slug, ticket.get("id"), ticket.get("title"))
    return index


def _session_paths(scope: str, index: dict) -> list[tuple[str, Path]]:
    """Liste ``(agent_id, path)`` des sessions à scanner selon le scope."""
    agents_dir = _agents_dir()
    if scope == "all":
        pairs = []
        for path in sorted(agents_dir.glob("*.session.json")):
            agent_id = path.name[: -len(".session.json")]
            pairs.append((agent_id, path))
        return pairs
    pairs = []
    for agent_id in index:
        path = agents_dir / f"{agent_id}.session.json"
        if path.exists():
            pairs.append((agent_id, path))
    return pairs


def _agents_dir() -> Path:
    from ..runtime import runner as _runner
    return _runner.AGENTS_DIR


def _search_session(path: Path, words: list[str], first: bytes) -> list[dict]:
    """Pré-filtre binaire puis parse : renvoie les extraits matchant (AND)."""
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    if first not in raw.lower():
        return []
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except (ValueError, TypeError):
        return []

    messages = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(messages, list):
        return []

    matches: list[dict] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str):
                snippet = _match_snippet(content, words)
                if snippet is not None:
                    matches.append({"role": "user", "snippet": snippet})
                    if len(matches) >= MAX_MATCHES_PER_AGENT:
                        return matches

    final = extract_final_answer(messages)
    if final and len(matches) < MAX_MATCHES_PER_AGENT:
        snippet = _match_snippet(final, words)
        if snippet is not None:
            matches.append({"role": "final_answer", "snippet": snippet})
    return matches


def _match_snippet(text: str, words: list[str]) -> str | None:
    """Renvoie un extrait ±80 chars si TOUS les mots sont présents (AND)."""
    low = text.casefold()
    if any(word not in low for word in words):
        return None
    pos = low.find(words[0])
    start = max(0, pos - SNIPPET_RADIUS)
    end = min(len(text), pos + len(words[0]) + SNIPPET_RADIUS)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet
