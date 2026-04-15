# [desc] Tests strip_unpaired_surrogates handles surrogate pairs, orphaned surrogates, and normal strings. [/desc]
"""Tests for strip_unpaired_surrogates — guards Windows paste crash.

Background: Windows clipboard paste can leave unpaired UTF-16 surrogates in
input strings, which Anthropic's SDK cannot encode to UTF-8 (TypeError on
`str.encode("utf-8")`). Before sending user input into the message stream,
we must either recombine valid surrogate pairs or drop orphaned surrogates.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bouzecode import strip_unpaired_surrogates


def _assert_utf8_safe(s: str) -> bytes:
    """Encoding to UTF-8 must not raise UnicodeEncodeError."""
    return s.encode("utf-8")


def test_ascii_passthrough():
    assert strip_unpaired_surrogates("hello world") == "hello world"


def test_regular_unicode_passthrough():
    # Accents, CJK, and BMP characters must pass through unchanged
    s = "café — 日本語 — naïve"
    assert strip_unpaired_surrogates(s) == s


def test_valid_surrogate_pair_recombined_into_emoji():
    # U+1F600 GRINNING FACE encoded as UTF-16 surrogate pair
    # High surrogate D83D, low surrogate DE00
    paired = "\ud83d\ude00"
    result = strip_unpaired_surrogates(paired)
    _assert_utf8_safe(result)
    assert result == "\U0001f600"


def test_emoji_string_roundtrip():
    original = "hello 😀 world 🎉"
    # Simulate the Windows-paste corruption by re-encoding via UTF-16 surrogates
    corrupted = original.encode("utf-16", "surrogatepass").decode("utf-16")
    result = strip_unpaired_surrogates(corrupted)
    _assert_utf8_safe(result)
    assert result == original


def test_orphan_high_surrogate_replaced():
    # Lone high surrogate without a low pair — must be dropped/replaced, not preserved
    orphan = "before\ud83dafter"
    result = strip_unpaired_surrogates(orphan)
    _assert_utf8_safe(result)  # must not raise
    assert "before" in result
    assert "after" in result


def test_orphan_low_surrogate_replaced():
    orphan = "x\udc00y"
    result = strip_unpaired_surrogates(orphan)
    _assert_utf8_safe(result)
    assert "x" in result and "y" in result


def test_mixed_valid_and_orphan():
    # One valid emoji pair + one orphan high surrogate
    mixed = "a\ud83d\ude00b\ud83dc"
    result = strip_unpaired_surrogates(mixed)
    _assert_utf8_safe(result)
    assert "\U0001f600" in result
    assert "a" in result and "b" in result and "c" in result


def test_empty_string():
    assert strip_unpaired_surrogates("") == ""
