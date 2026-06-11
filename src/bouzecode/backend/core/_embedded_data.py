# [desc] Loads system prompt templates and text data from data/ and system_prompts/ directories at import time [/desc]
"""Embedded text data — loaded from data/ directory at import time."""
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "system_prompts"


def _load(filename: str) -> str:
    return (_DATA_DIR / filename).read_text(encoding="utf-8")


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


SYSTEM_PROMPT_TEMPLATE: str = _load_prompt("01_main_system_prompt.txt")
LOGO_TEXT: str = _load("logo.txt")

THINK_OUT_LOUD_PROMPT: str = _load_prompt("02_think_out_loud.txt")
WINDOWS_PLATFORM_HINTS: str = _load_prompt("04_windows_platform_hints.txt")
PLAN_MODE_TEMPLATE: str = _load_prompt("05_plan_mode.txt")
MEMORY_CONSOLIDATION_PROMPT: str = _load_prompt("06_memory_consolidation.txt")
TOOL_EXAMPLES_XML: str = _load_prompt("07_tool_examples_xml.txt")
TOOL_EXAMPLES_JSON: str = _load_prompt("07_tool_examples_json.txt")
COMPACTION_SYSTEM_PROMPT: str = "You are a concise summarizer."
