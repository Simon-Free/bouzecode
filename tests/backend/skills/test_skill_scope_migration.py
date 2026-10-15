# [desc] The migration net: every skill the flat-priority loader resolved before still resolves, to the same file, on the real installation. [/desc]
"""Scope must not lose a single skill.

A skill that silently stops being found is a worse regression than the monorepo pollution
this feature fixes, so the guarantee is asserted over the REAL installation — the actual
`.bouzecode/skills`, `~/.bouzecode/skills`, `~/.claude/skills` and builtins of the machine
running the suite — not over a fixture that would only prove the fixture.

`_historical_resolution` below is the loader exactly as it was: a flat priority list of
storage locations, last writer wins. It is the reference the new resolver must cover.

One exception, and only one: a skill DELIBERATELY given a `scope:` is meant to disappear
outside its tree — that is the whole point of the feature. Those names are listed in
`INTENTIONALLY_SCOPED`, with the reason, so the net keeps catching ACCIDENTAL losses (the
regression that matters) without failing on the intended ones.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bouzecode.backend.core.config import CONFIG_DIR
from bouzecode.backend.core.paths import get_extra_dirs
from bouzecode.backend.tools.skill import loader as skill_loader
from bouzecode.backend.tools.skill import load_skills


# Skills deliberately restricted to one project tree: their absence from a cwd outside
# that tree is the feature working, not a loss. Every entry states WHY it was scoped, so a
# future reader can tell an intended scope from a bug — and the test below re-checks that
# each of them really does declare a `scope:`, keeping this list from becoming a dustbin.
INTENTIONALLY_SCOPED = {
    "ajout-competence":
        "gameplay of the Tomatoes Attack game — code lives in PycharmProjects/tomatoes_attack",
    "run-tests":
        "pytest layout and fixtures specific to demo_application",
    "demo-group-orchestration/mep-workflow":
        "production-deployment workflow of the demo/demo-group datascience projects",
    "pptx-template":
        "corporate slide-factory contract, implemented in demo_application (focus/agents/tools/"
        "pptx_*.py) AND in bouzecode_plugins (demo-pptx-plugin) — hence scoped to demo",
    "demodb-sql-macros":
        "DEMODB SQL macros, implemented in demo_application (focus/agents/tools/sql_macros.py)"
        " AND in bouzecode_plugins (demo-demodb-query-plugin) — hence scoped to demo",
    "skills-powerbi-refacto":
        "refactoring patterns for the demo Power BI models (Analyse_Trafic *.pbit at the "
        "demo root, demo-pbi-plugin) — meaningless outside that tree",
}


# Les deux filets ci-dessous portent sur le store PERSONNEL de l'utilisateur
# (`~/.bouzecode/skills`, où vivent les skills demo / tomatoes_attack). Sur une machine
# qui n'a pas ce store (CI, poste neuf), ils ne prouveraient rien : on les saute,
# explicitement, au lieu de les laisser échouer ou passer à vide.
_REAL_USER_STORE = (CONFIG_DIR / "skills").is_dir()
_requires_real_user_store = pytest.mark.skipif(
    not _REAL_USER_STORE,
    reason="store personnel ~/.bouzecode/skills absent : filet valable sur le poste réel seulement")

def _historical_resolution() -> dict[str, str]:
    """{name: file_path} as the pre-scope loader produced it. The migration reference."""
    paths = [(d / "skills", "extra") for d in get_extra_dirs()] + [
        (Path.cwd() / ".bouzecode" / "skills", "project"),
        (CONFIG_DIR / "skills", "user"),
        (Path.home() / ".claude" / "skills", "claude"),
    ]
    resolved = {skill.name: skill.file_path for skill in skill_loader._BUILTIN_SKILLS}
    for skill_dir, source in reversed(paths):
        for markdown in skill_loader._iter_skill_files(skill_dir):
            skill = skill_loader._parse_skill_file(markdown, source=source)
            if skill:
                resolved[skill.name] = skill.file_path
    return resolved


@pytest.fixture(scope="module")
def before_and_after() -> tuple[dict[str, str], dict[str, str]]:
    return _historical_resolution(), {s.name: s.file_path for s in load_skills()}


def test_the_real_installation_has_skills_to_migrate(before_and_after):
    """Guard: an empty inventory would make every assertion below vacuously true."""
    before, _ = before_and_after
    assert len(before) > 10, f"only {len(before)} skills found — inventory not representative"


def test_no_skill_stops_being_found(before_and_after):
    """Every name the old loader resolved is still resolved, bar the deliberately scoped."""
    before, after = before_and_after
    assert sorted(set(before) - set(after) - set(INTENTIONALLY_SCOPED)) == []


@_requires_real_user_store
def test_every_allowlisted_skill_really_declares_a_scope(before_and_after):
    """The allowlist may only cover skills that were actually scoped on purpose.

    Without this, a skill deleted from disk or broken by a malformed frontmatter would be
    silently absolved by its allowlist entry instead of failing the test above.
    """
    before, _ = before_and_after
    for name, reason in INTENTIONALLY_SCOPED.items():
        assert name in before, f"'{name}' no longer exists on disk — stale allowlist entry"
        skill = skill_loader._parse_skill_file(Path(before[name]))
        assert skill is not None, f"'{name}' no longer parses ({before[name]})"
        assert skill.scope, f"'{name}' is allowlisted ({reason}) but declares no scope:"


def test_no_skill_silently_resolves_to_a_different_file(before_and_after):
    """A name that used to load file A must not quietly start loading file B."""
    before, after = before_and_after
    moved = {name: (before[name], after[name])
             for name in set(before) & set(after) if before[name] != after[name]}
    assert moved == {}


def test_the_builtin_skills_all_survive():
    """The 6 builtins carry no scope, so they stay global and lowest-priority."""
    builtin_names = {s.name for s in skill_loader._BUILTIN_SKILLS}
    resolved = {s.name for s in load_skills()}
    assert builtin_names, "no builtin skills registered"
    assert builtin_names <= resolved


@_requires_real_user_store
def test_a_skill_in_the_global_user_store_stays_global(tmp_path, monkeypatch):
    """`~/.bouzecode/skills` gets NO implicit scope: an unscoped skill behaves as before.

    This is the safety rail. Deducing a scope there would hide the whole global store
    from any agent not working inside the home directory.
    """
    global_names = {s.name for s in load_skills() if not s.scope}
    assert len(global_names) > 10, "the global stores look empty — assertion would be vacuous"

    unrelated = tmp_path / "unrelated_project"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    assert global_names <= {s.name for s in load_skills()}


def test_the_project_claude_skills_directory_is_now_read():
    """`<projet>/.claude/skills` was referenced by other skills yet never loadable."""
    project_claude = Path.cwd() / ".claude" / "skills"
    if not project_claude.is_dir():
        pytest.skip("this checkout has no <projet>/.claude/skills")
    expected = {skill.name for markdown in skill_loader._iter_skill_files(project_claude)
                for skill in [skill_loader._parse_skill_file(markdown, source="project")]
                if skill}
    assert expected
    assert expected <= {s.name for s in load_skills()}
