"""Contract tests: guaranteed sections + the real agent/README.md is a valid fixture."""

from pathlib import Path

from readme_sync.contract import REQUIRED_SECTIONS, validate

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_contract_declares_guaranteed_sections():
    for section in ("purpose", "Subfolders", "Module Reference"):
        assert section in REQUIRED_SECTIONS


def test_agent_readme_satisfies_contract():
    agent_readme = REPO_ROOT / "src" / "bouzecode" / "backend" / "agent" / "README.md"
    md = agent_readme.read_text(encoding="utf-8")
    violations = validate(md)
    assert violations == [], f"agent/README.md violates the contract: {violations}"
