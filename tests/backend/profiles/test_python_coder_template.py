from pathlib import Path

import yaml

_PROFILE = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "bouzecode"
    / "backend"
    / "profiles"
    / "builtin"
    / "coder.yaml"
)

_SECTIONS = [
    "## 1. Résumé",
    "## 2. Cause / plan (vulgarisé)",
    "## 3. Tests ajoutés pour reproduire / valider",
    "## 4. Modifications (ordre logique)",
    "## 5. Diffs des fichiers de code",
    "## 6. Nouveaux tests / corrections (test_*.py)",
]


def _system_prompt_extra() -> str:
    data = yaml.safe_load(_PROFILE.read_text(encoding="utf-8"))
    extra = data.get("system_prompt_extra", "")
    assert extra, "coder.yaml has no system_prompt_extra"
    return extra


def test_template_has_all_six_sections():
    extra = _system_prompt_extra()
    for title in _SECTIONS:
        assert title in extra, f"missing FinalAnswer section title: {title!r}"


def test_template_sections_in_order():
    extra = _system_prompt_extra()
    positions = [extra.find(title) for title in _SECTIONS]
    assert all(p >= 0 for p in positions), "some section title missing"
    assert positions == sorted(positions), (
        "FinalAnswer section titles are not in the expected 1..6 order: "
        f"{positions}"
    )
