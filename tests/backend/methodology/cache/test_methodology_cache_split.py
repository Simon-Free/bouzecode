# [desc] Tests pure A/B split logic and system block generation for methodology cache prefixing. [/desc]
"""Verify the pure A/B split of the methodology note.

A = snapshot from last turn (cache_read), B = delta appended since.
Replace fallback: current does not start with snapshot → all fresh, no cached prefix.
"""
from __future__ import annotations

from bouzecode.backend.context_manager.methodology import (
    build_methodology_system_blocks,
    split_methodology_for_cache,
)


_CC = {"type": "ephemeral"}
_HEADER = "[METHODOLOGY — your persistent working memory across turns]\n"


# --- Pure split logic -------------------------------------------------------

def test_split_first_turn_empty_snapshot():
    old, new = split_methodology_for_cache("## step 1\n", "")
    assert old == ""
    assert new == "## step 1\n"


def test_split_unchanged_methodology_full_prefix():
    old, new = split_methodology_for_cache("## step 1\n", "## step 1\n")
    assert old == "## step 1\n"
    assert new == ""


def test_split_appended_methodology():
    current = "## step 1\n\n## step 2\n"
    snapshot = "## step 1\n"
    old, new = split_methodology_for_cache(current, snapshot)
    assert old == "## step 1\n"
    assert new == "\n## step 2\n"


def test_split_replaced_methodology_falls_back_to_all_fresh():
    old, new = split_methodology_for_cache("## step 2\n", "## step 1\n")
    assert old == ""
    assert new == "## step 2\n"


def test_split_empty_methodology_returns_empty():
    assert split_methodology_for_cache("", "") == ("", "")
    assert split_methodology_for_cache("", "## step 1\n") == ("", "")


# --- build_methodology_system_blocks output ---------------------------------

def test_build_blocks_empty_methodology_returns_nothing():
    blocks, delta = build_methodology_system_blocks("", "", _CC)
    assert blocks == []
    assert delta == ""


def test_build_blocks_first_turn_puts_full_in_system_no_delta():
    text = "## User\nhello\n"
    blocks, delta = build_methodology_system_blocks(text, "", _CC)
    assert len(blocks) == 1
    assert blocks[0]["cache_control"] == _CC
    assert blocks[0]["text"] == _HEADER + text
    assert delta == ""


def test_build_blocks_unchanged_methodology_no_delta():
    text = "## User\nhello\n"
    blocks, delta = build_methodology_system_blocks(text, text, _CC)
    assert len(blocks) == 1
    assert blocks[0]["text"] == _HEADER + text
    assert delta == ""


def test_build_blocks_appended_methodology_splits_old_and_new():
    old_part = "## User\nhello\n"
    new_part = "\n## snippet foo\nbody\n"
    current = old_part + new_part
    blocks, delta = build_methodology_system_blocks(current, old_part, _CC)
    assert len(blocks) == 1
    assert blocks[0]["text"] == _HEADER + old_part
    assert blocks[0]["cache_control"] == _CC
    assert delta == new_part


def test_build_blocks_replaced_methodology_no_delta_all_in_system():
    current = "## User\ndifferent content\n"
    snapshot = "## User\nold content\n"
    blocks, delta = build_methodology_system_blocks(current, snapshot, _CC)
    assert len(blocks) == 1
    assert blocks[0]["text"] == _HEADER + current
    assert delta == ""


def test_build_blocks_cache_control_passed_through():
    cc_1h = {"type": "ephemeral", "ttl": "1h"}
    blocks, _ = build_methodology_system_blocks("X", "", cc_1h)
    assert blocks[0]["cache_control"] == cc_1h
