# [desc] Tests that system prompt files exist in correct location and load properly via _embedded_data
# <tool_use name="FinalAnswer" id="r1"><param name="answer">Tests that system prompt files exist in correct location and load properly via _embedded_data</param></tool_use> [/desc]
"""Test that the system prompt is correctly placed in system_prompts/ and loaded."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
# Compact example-first noyau: the identity line is a single dense line.
EXPECTED_FIRST_LINE = "Tu es Bouzecode. Penser/répondre FR, code EN. Plateforme : {platform}"


def test_system_prompt_in_system_prompts_dir():
    """The main system prompt must live in system_prompts/01_main_system_prompt.txt with correct content."""
    prompts_file = PROJECT_ROOT / "src" / "system_prompts" / "01_main_system_prompt.txt"
    assert prompts_file.exists(), f"File not found: {prompts_file}"
    content = prompts_file.read_text(encoding="utf-8")
    actual_first_line = content.strip().splitlines()[0]
    assert actual_first_line == EXPECTED_FIRST_LINE, (
        f"01_main_system_prompt.txt has wrong content.\n"
        f"Expected first line: {EXPECTED_FIRST_LINE!r}\n"
        f"Got: {actual_first_line!r}"
    )


def test_embedded_data_loads_from_system_prompts():
    """SYSTEM_PROMPT_TEMPLATE must be loaded via _load_prompt (from system_prompts/ dir)."""
    embedded_file = PROJECT_ROOT / "src" / "bouzecode" / "backend" / "core" / "_embedded_data.py"
    source = embedded_file.read_text(encoding="utf-8")
    assert '_load_prompt("01_main_system_prompt.txt")' in source, (
        "_embedded_data.py should load SYSTEM_PROMPT_TEMPLATE via _load_prompt('01_main_system_prompt.txt')"
    )


def test_system_prompt_loaded_is_version2():
    """SYSTEM_PROMPT_TEMPLATE must start with the v2 prompt."""
    from bouzecode.backend.core import _embedded_data
    import importlib
    importlib.reload(_embedded_data)

    actual_first_line = _embedded_data.SYSTEM_PROMPT_TEMPLATE.strip().splitlines()[0]
    assert actual_first_line == EXPECTED_FIRST_LINE, (
        f"SYSTEM_PROMPT_TEMPLATE starts with wrong content.\n"
        f"Expected: {EXPECTED_FIRST_LINE!r}\n"
        f"Got:      {actual_first_line!r}"
    )
