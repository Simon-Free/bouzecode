# [desc] The terminal answers in English by default, and in French when BOUZECODE_LANG asks. [/desc]
"""The terminal used to speak French while the README and the web UI spoke English.

It now answers in English by default; `BOUZECODE_LANG=fr` brings back the exact
wording it used to print, for whoever relied on it.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.commands.agent_upgrade import cmd_agent_upgrade
from bouzecode.ui.messages import MESSAGES, msg, terminal_language

FRENCH = {"BOUZECODE_LANG": "fr"}
NO_PREFERENCE: dict[str, str] = {}

# Accented letters give an untranslated French entry away in the English column. The
# English wording of this UI has no legitimate use for them.
FRENCH_ACCENTS = "àâçéèêëîïôùûüœÀÂÇÉÈÊËÎÏÔÙÛÜŒ"


def test_a_user_who_asked_for_nothing_reads_english():
    assert terminal_language(NO_PREFERENCE) == "en"
    assert msg("ripgrep.missing", env=NO_PREFERENCE) == (
        "ripgrep (rg) not found — downloading from GitHub..."
    )


def test_bouzecode_lang_fr_brings_back_the_former_french_wording():
    assert terminal_language(FRENCH) == "fr"
    assert msg("ripgrep.missing", env=FRENCH) == (
        "ripgrep (rg) non trouvé — téléchargement depuis GitHub..."
    )
    assert msg("ripgrep.installed", env=FRENCH) == "ripgrep installé avec succès."


@pytest.mark.parametrize("value", ["fr", "FR", "fr_FR.UTF-8", "fr-BE", "  fr  "])
def test_every_spelling_of_french_is_accepted(value):
    """A value copied straight out of LANG must work, not just the bare "fr"."""
    assert terminal_language({"BOUZECODE_LANG": value}) == "fr"


@pytest.mark.parametrize("value", ["", "en", "en_GB.UTF-8", "de", "1"])
def test_anything_else_falls_back_to_english(value):
    """A typo must not fail a launch, and must not silently pick another language."""
    assert terminal_language({"BOUZECODE_LANG": value}) == "en"


def test_placeholders_are_filled_in_both_languages():
    assert msg("ripgrep.downloading", env=NO_PREFERENCE, version="14.1.1") == (
        "  Downloading ripgrep 14.1.1..."
    )
    assert msg("ripgrep.downloading", env=FRENCH, version="14.1.1") == (
        "  Téléchargement de ripgrep 14.1.1..."
    )


def test_no_message_is_left_untranslated():
    """Both columns are filled, and the English one carries no French accent."""
    empty = [key for key, (en, fr) in MESSAGES.items() if not en.strip() or not fr.strip()]
    assert empty == []

    accented = [key for key, (en, _) in MESSAGES.items()
                if any(letter in en for letter in FRENCH_ACCENTS)]
    assert accented == [], "these English messages still read as French"


def test_an_unknown_key_fails_loudly():
    """A message rendered as its own key is a defect that reaches the user's screen."""
    with pytest.raises(KeyError):
        msg("nope.not.a.message")


def test_agent_upgrade_names_an_unknown_agent_in_english(capsys, monkeypatch):
    """A real command, on its real output path — not just the table."""
    monkeypatch.delenv("BOUZECODE_LANG", raising=False)

    cmd_agent_upgrade("definitely-not-an-agent", None, {})

    assert "Unknown agent: definitely-not-an-agent" in capsys.readouterr().err


def test_agent_upgrade_names_an_unknown_agent_in_french(capsys, monkeypatch):
    monkeypatch.setenv("BOUZECODE_LANG", "fr")

    cmd_agent_upgrade("definitely-not-an-agent", None, {})

    assert "Agent inconnu : definitely-not-an-agent" in capsys.readouterr().err
