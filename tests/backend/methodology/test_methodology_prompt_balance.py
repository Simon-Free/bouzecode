from pathlib import Path

import pytest

PROMPTS_DIR = (
    Path(__file__).resolve().parents[3] / "src" / "system_prompts"
)
MAIN_PROMPT = PROMPTS_DIR / "01_main_system_prompt.txt"
XML_EXAMPLES = PROMPTS_DIR / "07_tool_examples_xml.txt"
JSON_EXAMPLES = PROMPTS_DIR / "07_tool_examples_json.txt"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_main_prompt_drops_length_cap():
    """La Discipline Methodology ne doit plus plafonner a 2-5 lignes."""
    text = _read(MAIN_PROMPT)
    assert "2-5 lignes" not in text
    assert "coût permanent" not in text


def test_main_prompt_keeps_anti_recopie():
    """Le garde-fou anti-recopie (append-only) doit rester present."""
    text = _read(MAIN_PROMPT).lower()
    assert "recopie" in text
    assert "append-only" in text


def _methodology_example_block(text: str) -> str:
    """Extrait le contenu de l'exemple Methodology de l'exemple-gabarit."""
    lower = text.lower()
    idx = lower.find("methodology")
    assert idx != -1, "exemple Methodology introuvable"
    # On prend une fenetre suffisante pour englober un bloc multi-lignes.
    return text[idx : idx + 800]


@pytest.mark.parametrize("path", [XML_EXAMPLES, JSON_EXAMPLES])
def test_methodology_example_is_multiline(path: Path):
    """L'exemple Methodology doit etre multi-lignes / multi-elements (>=4)."""
    text = _read(path)
    block = _methodology_example_block(text)
    # Plusieurs marqueurs distincts : todolist, decision, etape, etc.
    # Le format XML a de vraies newlines ; le JSON les echappe en "\n".
    newline_count = block.count(chr(10)) + block.count("\\n")
    assert newline_count >= 3, (
        f"exemple Methodology trop court dans {path.name} "
        f"(newlines={newline_count})"
    )
