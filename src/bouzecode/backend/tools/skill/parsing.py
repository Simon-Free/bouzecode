# [desc] Turns one skill markdown file into a SkillDef, and substitutes $ARGUMENTS placeholders at invocation time. [/desc]
"""Parsing a single skill file, and rendering its body with arguments.

Split out of loader.py, which now only answers "which skills exist and which one wins".
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .frontmatter import (
    UnterminatedFrontmatterError,
    parse_frontmatter_fields,
    split_frontmatter,
)
from .scope import implicit_scope_for_file, resolve_declared_scope

if TYPE_CHECKING:
    from .loader import SkillDef


def _parse_list_field(value: str) -> list[str]:
    """Parse YAML-like list: ``[a, b, c]`` or ``"a, b, c"``."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [item.strip().strip('"').strip("'") for item in value.split(",") if item.strip()]


def _parse_skill_file(path: Path, source: str = "user") -> Optional["SkillDef"]:
    """Parse a markdown file with ``---`` frontmatter into a SkillDef.

    A malformed frontmatter is refused wholesale and reported on stderr, never
    half-loaded: one bad file in ``~/.bouzecode/skills`` must not abort startup.

    Frontmatter fields:
        name, description, triggers, tools / allowed-tools,
        when_to_use, argument-hint, arguments, model,
        user-invocable, context, scope, scope_label
    """
    from .loader import SkillDef

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    try:
        split = split_frontmatter(text)
    except UnterminatedFrontmatterError as error:
        print(f"[skill] ignorée, {path}: {error}", file=sys.stderr)
        return None
    if split is None:
        return None

    frontmatter_raw, prompt = split
    fields = parse_frontmatter_fields(frontmatter_raw)

    name = fields.get("name", "")
    if not name:
        return None

    # allowed-tools wins over tools if present
    tools_raw = fields.get("allowed-tools", fields.get("tools", ""))
    tools = _parse_list_field(tools_raw) if tools_raw else []

    triggers_raw = fields.get("triggers", "")
    triggers = _parse_list_field(triggers_raw) if triggers_raw else [f"/{name}"]

    arguments_raw = fields.get("arguments", "")
    arguments = _parse_list_field(arguments_raw) if arguments_raw else []

    user_invocable_raw = fields.get("user-invocable", "true")
    user_invocable = user_invocable_raw.lower() not in ("false", "0", "no")

    context = fields.get("context", "inline").strip().lower()
    if context not in ("inline", "fork"):
        context = "inline"

    # Explicit scope beats the one deduced from where the file sits.
    scope = resolve_declared_scope(fields.get("scope", ""), path) or implicit_scope_for_file(path)
    scope_label = fields.get("scope_label", "").strip() or (Path(scope).name if scope else "")

    return SkillDef(
        name=name,
        description=fields.get("description", ""),
        triggers=triggers,
        tools=tools,
        prompt=prompt,
        file_path=str(path),
        when_to_use=fields.get("when_to_use", ""),
        argument_hint=fields.get("argument-hint", ""),
        arguments=arguments,
        model=fields.get("model", ""),
        user_invocable=user_invocable,
        context=context,
        source=source,
        scope=scope,
        scope_label=scope_label,
    )


def substitute_arguments(prompt: str, args: str, arg_names: list[str]) -> str:
    """Replace $ARGUMENTS (whole args string) and $ARG_NAME placeholders.

    Named args are positional: first word → first name, etc.
    """
    result = prompt.replace("$ARGUMENTS", args)
    arg_values = args.split()
    for i, arg_name in enumerate(arg_names):
        placeholder = f"${arg_name.upper()}"
        value = arg_values[i] if i < len(arg_values) else ""
        result = result.replace(placeholder, value)
    return result
