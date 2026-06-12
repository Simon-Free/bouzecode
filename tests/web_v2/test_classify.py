# [desc] Tests for prompt classification service: parsing, fallback on error/garbage, monkeypatch LLM stream. [/desc]
"""Tests for bouzecode.web_v2.services.classify — monkeypatch, no mock.patch."""
from __future__ import annotations

import pytest

from bouzecode.web_v2.services import classify as classify_mod
from bouzecode.web_v2.services.classify import (
    _parse_classify_response,
    classify_prompt,
)


class FakeEvent:
    def __init__(self, text: str):
        self.text = text


def _fake_stream_success(**kwargs):
    """Simulates a well-formatted LLM response."""
    yield FakeEvent("TITLE: Corriger le bug d'affichage\n")
    yield FakeEvent("PROJECT: calypso\n")
    yield FakeEvent("TYPOLOGY: focus\n")


def _fake_stream_garbage(**kwargs):
    """Simulates a poorly formatted LLM response."""
    yield FakeEvent("Je ne sais pas quoi répondre, voici du blabla.")


def _fake_stream_raises(**kwargs):
    raise ConnectionError("network down")


PROJECTS = [{"slug": "calypso"}, {"slug": "other"}]
TYPOLOGIES = [{"name": "default"}, {"name": "focus"}, {"name": "refacto"}]


def test_classify_prompt_success(monkeypatch):
    monkeypatch.setattr(classify_mod, "dispatch_stream", _fake_stream_success)
    result = classify_prompt("Fix the display bug in the navbar", PROJECTS, TYPOLOGIES)
    assert result["title"] == "Corriger le bug d'affichage"
    assert result["project_slug"] == "calypso"
    assert result["typology"] == "focus"


def test_classify_prompt_garbage_response(monkeypatch):
    monkeypatch.setattr(classify_mod, "dispatch_stream", _fake_stream_garbage)
    result = classify_prompt("Fix the display bug in the navbar", PROJECTS, TYPOLOGIES)
    # Fallback: title = first line of prompt[:80], project = None, typology = default
    assert result["title"] == "Fix the display bug in the navbar"
    assert result["project_slug"] is None
    assert result["typology"] == "default"


def test_classify_prompt_exception_fallback(monkeypatch):
    monkeypatch.setattr(classify_mod, "dispatch_stream", _fake_stream_raises)
    result = classify_prompt("Something\nwith multiple lines", PROJECTS, TYPOLOGIES)
    assert result["title"] == "Something"
    assert result["project_slug"] is None
    assert result["typology"] == "default"


def test_classify_prompt_empty():
    """Empty prompt returns fallback immediately without LLM call."""
    result = classify_prompt("", PROJECTS, TYPOLOGIES)
    assert result["title"] == ""
    assert result["project_slug"] is None
    assert result["typology"] == "default"


def test_parse_classify_response_valid():
    text = "TITLE: Mon titre\nPROJECT: calypso\nTYPOLOGY: refacto"
    result = _parse_classify_response(text, PROJECTS, TYPOLOGIES)
    assert result == {"title": "Mon titre", "project_slug": "calypso", "typology": "refacto"}


def test_parse_classify_response_unknown_project():
    text = "TITLE: Mon titre\nPROJECT: unknown_proj\nTYPOLOGY: focus"
    result = _parse_classify_response(text, PROJECTS, TYPOLOGIES)
    assert result["project_slug"] is None


def test_parse_classify_response_unknown_typology():
    text = "TITLE: Mon titre\nPROJECT: calypso\nTYPOLOGY: wizard"
    result = _parse_classify_response(text, PROJECTS, TYPOLOGIES)
    assert result["typology"] == "default"


def test_parse_classify_response_empty():
    result = _parse_classify_response("", PROJECTS, TYPOLOGIES)
    assert result["title"] == ""
    assert result["project_slug"] is None
    assert result["typology"] == "default"


def test_parse_classify_response_case_insensitive():
    text = "title: Mon Titre\nproject: calypso\ntypology: focus"
    result = _parse_classify_response(text, PROJECTS, TYPOLOGIES)
    assert result["title"] == "Mon Titre"
    assert result["project_slug"] == "calypso"
    assert result["typology"] == "focus"


def test_parse_classify_response_with_none_project():
    text = "TITLE: Un titre\nPROJECT: NONE\nTYPOLOGY: default"
    result = _parse_classify_response(text, PROJECTS, TYPOLOGIES)
    assert result["project_slug"] is None
