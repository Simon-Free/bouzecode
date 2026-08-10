# [desc] Reads tool names out of prose and computes, from the LIVE registry, what replaces a tool an agent cannot call. [/desc]
"""Tool names inside text — citations and substitutes.

Two questions share one rule here, so they share one module:

* which tools does a piece of prompt-layer text NAME? (`tool_names_cited`) — used by
  the prompt/registry conformity test, so the harness can never prescribe a tool it
  forbids;
* when an agent calls a tool it does not have, which of the tools it DOES have comes
  closest? (`suggest_substitutes`) — computed from the live registry and from the
  cross-references the schemas already carry, never from a hardcoded mapping (a
  hardcoded mapping rots exactly like the prescriptions it is meant to repair).
"""
from __future__ import annotations

import json
import re
from typing import Iterable, List, Sequence, Set


def _is_compound(name: str) -> bool:
    """True for a multi-word CamelCase name (RunPythonTest, BashOutput)."""
    return sum(1 for ch in name if ch.isupper()) > 1


def _citation_pattern(name: str) -> str:
    """A compound name is unambiguous bare; a single word (Agent, Read, Skill) is an
    ordinary French/English word too, so it only counts when marked up as a tool:
    `Name`, `Name(`, **Name** or Name(...)."""
    escaped = re.escape(name)
    if _is_compound(name):
        return rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])"
    return rf"(?:`{escaped}[`(]|\*\*{escaped}\*\*|(?<![A-Za-z0-9_`]){escaped}\()"


def tool_names_cited(text: str, known_names: Iterable[str]) -> Set[str]:
    """Return the tool names from *known_names* that *text* names as tools."""
    if not text:
        return set()
    return {name for name in known_names if re.search(_citation_pattern(name), text)}


def _schema_text(name: str) -> str:
    from .tool_registry import get_tool

    tool = get_tool(name)
    return json.dumps(tool.schema, ensure_ascii=False) if tool is not None else ""


def suggest_substitutes(refused: str, available: Sequence[str], limit: int = 3) -> List[str]:
    """Rank the *available* tools by how closely they relate to the *refused* one.

    The ranking uses the cross-references the tool schemas already publish — the
    refused tool's own description naming another tool, or an available tool's
    description naming the refused one (this is how `Bash` surfaces for a refused
    `RunPythonTest`). Nothing is hardcoded, so a renamed or removed tool can never
    be recommended: the candidates come from the registry the agent actually has.
    """
    available = [n for n in available if n != refused]
    cited_by_refused = tool_names_cited(_schema_text(refused), available)
    scores: dict[str, int] = {}
    for name in available:
        score = 2 if name in cited_by_refused else 0
        if refused in tool_names_cited(_schema_text(name), [refused]):
            score += 2
        if score:
            scores[name] = score
    ranked = sorted(scores, key=lambda n: (-scores[n], n))
    return ranked[:limit]


def unavailable_tool_message(refused: str, available: Sequence[str], missing: bool = False) -> str:
    """The message an agent reads when it calls a tool it cannot call.

    It must be TERMINAL (the agent cannot enable anything itself, so retrying is pure
    loss) and ACTIONABLE (it names tools that really are in this agent's registry).
    """
    available = sorted(available)
    head = (
        f"Error: l'outil `{refused}` n'existe pas dans ce harnais."
        if missing else
        f"Error: l'outil `{refused}` n'est pas disponible pour cet agent."
    )
    lines = [
        f"{head} Tu ne peux PAS l'activer toi-même : `/tools` est une commande "
        f"utilisateur, pas un outil. N'insiste pas — rappeler `{refused}` échouera "
        "à l'identique et coûtera un tour pour rien.",
    ]
    closest = suggest_substitutes(refused, available)
    if closest:
        lines.append("Le plus proche parmi tes outils : " + ", ".join(f"`{n}`" for n in closest) + ".")
    lines.append("Tous les outils dont tu disposes : " + ", ".join(available) + ".")
    lines.append(
        "Si aucun ne convient, ne contourne pas : clôture par FinalAnswer en signalant "
        "le manque, ou demande l'activation via AskUserQuestion."
    )
    return "\n".join(lines)
