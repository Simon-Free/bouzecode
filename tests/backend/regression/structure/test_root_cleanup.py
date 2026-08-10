"""Verify root cleanup: dead files removed, thinking_parser moved."""
import importlib
import pytest


def test_setup_tools_removed():
    """setup_tools.py must no longer exist as importable module."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("bouzecode.backend.setup_tools")


def test_subagent_shim_removed():
    """subagent.py shim must no longer exist."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("bouzecode.backend.subagent")


def test_thinking_parser_moved():
    """thinking_parser must be importable from new location."""
    from bouzecode.backend.agent.thinking_parser import (
        ThinkingStreamParser, LoopDetector,
        strip_thinking_tags, strip_tool_use_xml,
        ThinkingDisciplineMonitor,
    )
    assert ThinkingStreamParser is not None


def test_thinking_parser_old_path_dead():
    """Old bouzecode.backend.thinking_parser path must be gone (moved to .agent)."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("bouzecode.backend.thinking_parser")
