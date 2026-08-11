"""End-to-end system verification for readme_sync.

Plays, as executed checks, the six verification points of the mission:
scan exclusions (2), real API generation (3), bootstrap guards (4),
navigation injection (5) and the root->subfolder->symbol chain (6).
Point 1 (the full suite green) is proven by running the suite itself.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from readme_sync.bootstrap import bootstrap_readme_map, maybe_bootstrap_readme
from readme_sync.contract import validate
from readme_sync.hashing import FolderState, iter_code_folders, scan
from readme_sync.propagate import create_root_map
from readme_sync.regen import api_key

REPO_ROOT = Path(__file__).resolve().parents[3]

try:
    from bouzecode.backend.tools.folder_desc.symbols import find_symbol
except ImportError:
    from bouzecode.backend.tools.folder_desc import find_symbol


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _subfolder_links(md: str) -> list[str]:
    links, in_section = [], False
    for line in md.splitlines():
        if line.strip() == "## Subfolders":
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            for m in re.finditer(r"\]\(([^)]+)\)", line):
                links.append(m.group(1))
    return links


# ---------------------------------------------------------------- point 2
def test_scan_excludes_venv_gitignore_and_empty(tmp_path):
    root = tmp_path / "app"
    _write(root / "mod.py", "def real_thing():\n    return 1\n")
    _write(root / "venvdir" / "pyvenv.cfg", "home = /usr\n")
    _write(root / "venvdir" / "junk.py", "x = 1\n")
    _write(root / "ignored" / "secret.py", "y = 2\n")
    _write(root / "empty" / "notes.txt", "no python here\n")
    _write(root / ".gitignore", "ignored/\n")
    subprocess.run(["git", "init"], cwd=root, capture_output=True)

    folders = {p.resolve() for p in iter_code_folders(root)}
    assert (root / "venvdir").resolve() not in folders, "venv must be excluded"
    assert (root / "ignored").resolve() not in folders, "gitignored dir must be excluded"

    flagged = {s.path.resolve() for s in scan(root) if s.needs_attention}
    assert (root / "empty").resolve() not in flagged, "no-.py folder must not be flagged"
    assert root.resolve() in flagged, "the real code folder must be flagged"


def test_bouzecode_check_is_reasonable(run_cli):
    """`--check` sur le vrai dépôt annonce un nombre de dossiers plausible.

    On lit le compte ANNONCÉ (« N folders scanned »). L'ancienne version prenait le plus
    grand nombre apparaissant dans la sortie : ça ne mesurait le nombre de dossiers que
    tant que le dépôt était désynchronisé et listait des dossiers stale. Une fois tout en
    phase, la sortie ne contenait plus que des petits compteurs et le test tombait.
    """
    rc, out, err = run_cli("--check", "--root", str(REPO_ROOT))
    output = out + err
    match = re.search(r"(\d+) folders scanned", output)
    assert match, f"le compte de dossiers doit être annoncé explicitement : {output!r}"
    total = int(match.group(1))
    assert 50 < total < 500, f"expected a sane folder count, got {total}: {output!r}"


# ---------------------------------------------------------------- point 4
def test_bootstrap_guards(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    _write(root / "a" / "x.py", "def fa():\n    return 1\n")
    _write(root / "b" / "y.py", "def fb():\n    return 2\n")

    capped = bootstrap_readme_map(root, max_folders=1)
    assert capped["skipped"] == "too_many_folders", capped
    assert capped["disabled"] is False

    wt = tmp_path / "worktree"
    _write(wt / "c" / "z.py", "def fc():\n    return 3\n")
    (wt / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
    assert bootstrap_readme_map(wt)["skipped"] == "worktree"

    monkeypatch.delenv("BOUZECODE_README_SYNC", raising=False)
    assert maybe_bootstrap_readme(root, cap=0).get("disabled") is not True

    monkeypatch.setenv("BOUZECODE_README_SYNC", "0")
    assert maybe_bootstrap_readme(root)["disabled"] is True


# ---------------------------------------------------------------- point 5
def test_navigation_injection_no_longer_depends_on_a_root_map(tmp_path, monkeypatch):
    """The injected protocol points at tools, so no map file needs to exist.

    The old block walked a `## Subfolders` table and was therefore injected only
    when a root map was on disk. Its replacement names `AgentsMap()` /
    `SymbolMap()`, which generate the maps on demand — nothing to probe for, so
    the section is unconditional. Only the global env switch can silence it
    (covered by tests/backend/agents_map/test_map_contract.py).
    """
    from bouzecode.backend.core.context import get_readme_navigation_section

    with_map = tmp_path / "withmap"
    with_map.mkdir()
    (with_map / "AGENTS.md").write_text(
        "# withmap/\n\nmap\n\n## Subfolders\n\n| Folder | Purpose |\n"
        "|--------|---------|\n| [a/](a/AGENTS.md) | thing |\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(with_map)
    with_map_section = get_readme_navigation_section()

    without = tmp_path / "nomap"
    without.mkdir()
    monkeypatch.chdir(without)
    without_map_section = get_readme_navigation_section()

    assert "# Codebase navigation" in with_map_section
    assert without_map_section == with_map_section
    assert "AgentsMap()" in without_map_section
    assert "SymbolMap(" in without_map_section
    assert "## Subfolders" not in without_map_section


# ---------------------------------------------------------------- points 3 & 6
@pytest.fixture(scope="module")
def generated_tree(tmp_path_factory):
    if api_key() is None:
        pytest.skip("no ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN in env")
    root = tmp_path_factory.mktemp("gen")
    _write(
        root / "billing" / "invoice.py",
        "def compute_shipping_total(items):\n"
        "    return sum(i for i in items)\n\n\n"
        "class InvoiceBuilder:\n"
        "    def build(self):\n        return {}\n",
    )
    _write(
        root / "billing" / "taxes.py",
        "def apply_vat(amount):\n    return amount * 1.2\n",
    )
    _write(
        root / "billing" / "reports" / "summary.py",
        "def render_monthly_report(rows):\n    return len(rows)\n",
    )
    result = bootstrap_readme_map(root, client=None)
    return root, result


@pytest.mark.llm
def test_real_generation_via_api(generated_tree):
    root, result = generated_tree
    assert "skipped" not in result, result

    code_folders = [f for f in iter_code_folders(root) if any(f.glob("*.py"))]
    for folder in code_folders:
        doc = folder / "AGENTS.md"
        assert doc.exists(), f"missing AGENTS.md in {folder}"
        assert validate(doc.read_text(encoding="utf-8")) == []

    billing_md = (root / "billing" / "AGENTS.md").read_text(encoding="utf-8")
    assert "compute_shipping_total" in billing_md, billing_md

    root_md = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Subfolders" in root_md
    assert _subfolder_links(root_md), "root map lists no subfolders"


@pytest.mark.llm
def test_navigation_three_hops(generated_tree):
    root, _ = generated_tree
    root_md = (root / "AGENTS.md").read_text(encoding="utf-8")
    links = _subfolder_links(root_md)
    assert links, "no subfolder links at root"

    billing_link = next(l for l in links if l.startswith("billing/"))
    leaf_readme = (root / billing_link).resolve()
    assert leaf_readme.exists(), leaf_readme
    leaf_md = leaf_readme.read_text(encoding="utf-8")

    assert "## Module Reference" in leaf_md
    assert "compute_shipping_total" in leaf_md

    invoice_py = str(root / "billing" / "invoice.py")
    span = find_symbol(invoice_py, "compute_shipping_total")
    assert span is not None, "symbol from README did not resolve in the file"
    start, end = span
    assert start >= 1 and end >= start
