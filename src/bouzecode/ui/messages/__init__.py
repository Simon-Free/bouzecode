# [desc] Terminal wording: English by default, French when BOUZECODE_LANG asks for it. [/desc]
"""What the terminal prints to a human, in English by default.

The README and the web UI speak English; the terminal was the last place that
answered in French. `BOUZECODE_LANG=fr` restores the wording it used to print, so
the operators who relied on it lose nothing.

SCOPE — only strings a *user* reads in a terminal live here. Comments, docstrings
and everything addressed to the model (system prompts, tool instructions) are not
translated and stay where they are: they are not part of the interface.

WHY A DICT AND A LOOKUP, and not gettext nor the web UI's i18n core: there are a few
dozen messages, and a terminal process reads its environment once at startup. The
browser needs a hot switch because a tab outlives the choice; a CLI run does not.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

from .agents import AGENT_MESSAGES
from .terminal import TERMINAL_MESSAGES

LANGUAGE_VAR = "BOUZECODE_LANG"
DEFAULT_LANGUAGE = "en"

# key -> (english, french). The two catalogues are disjoint by construction: one
# covers the terminal UI itself, the other the /agent* commands.
MESSAGES: dict[str, tuple[str, str]] = {**TERMINAL_MESSAGES, **AGENT_MESSAGES}


def terminal_language(env: Mapping[str, str] | None = None) -> str:
    """`"fr"` when BOUZECODE_LANG asks for French, `"en"` otherwise.

    Any value starting with `fr` counts (`fr`, `FR`, `fr_FR.UTF-8`, `fr-BE`) so a
    value copied straight from `LANG` works. Every other value — including a typo —
    falls back to English rather than failing a launch over a spelling.
    """
    requested = (os.environ if env is None else env).get(LANGUAGE_VAR, "")
    return "fr" if requested.strip().lower().startswith("fr") else DEFAULT_LANGUAGE


def msg(key: str, *, env: Mapping[str, str] | None = None, **fields: object) -> str:
    """The message registered under `key`, in the terminal language, `.format`-ed.

    An unknown key raises `KeyError` here and now: a message that quietly renders as
    its own key is a defect that ships all the way to the user's screen.
    """
    english, french = MESSAGES[key]
    template = french if terminal_language(env) == "fr" else english
    return template.format(**fields) if fields else template
