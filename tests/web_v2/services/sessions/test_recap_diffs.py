"""Tests de recap_diffs.build_recap_payload : tri/regroupement/isolation tests/fallback.

Fonction pure → fixtures = vrais fragments de `git diff` (avec `new file mode` pour
un test neuf, `--- a/... +++ b/...` pour un fichier modifié)."""
from bouzecode.web_v2.services.sessions.recap_diffs import (
    build_recap_payload,
    split_unified_diff,
)


def _mod_diff(path: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"index 1111111..2222222 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1,3 +1,3 @@\n"
        " context\n"
        "-old line\n"
        "+new line\n"
    )


def _new_diff(path: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        "new file mode 100644\n"
        "index 0000000..3333333\n"
        f"--- /dev/null\n"
        f"+++ b/{path}\n"
        "@@ -0,0 +1,2 @@\n"
        "+first\n"
        "+second\n"
    )


def test_split_extracts_one_block_per_file_with_flags():
    diff = _mod_diff("src/a.py") + _new_diff("tests/test_a.py")
    blocks = split_unified_diff(diff)
    assert [b["file"] for b in blocks] == ["src/a.py", "tests/test_a.py"]
    assert blocks[0]["is_test"] is False and blocks[0]["is_new"] is False
    assert blocks[1]["is_test"] is True and blocks[1]["is_new"] is True
    # chaque patch est autonome (contient son propre en-tête diff --git).
    assert blocks[0]["patch"].startswith("diff --git a/src/a.py")
    assert blocks[1]["patch"].startswith("diff --git a/tests/test_a.py")


def test_split_empty_diff_returns_empty():
    assert split_unified_diff("") == []
    assert split_unified_diff("   \n  ") == []


def test_ordering_follows_recap_changes_then_other_then_tests():
    # Diff dans un ordre VOLONTAIREMENT différent de recap.changes.
    diff = (
        _new_diff("tests/test_beta.py")       # test neuf
        + _mod_diff("src/second.py")          # dans changes (2e)
        + _mod_diff("src/orphan.py")          # hors changes → « Autres modifications »
        + _mod_diff("src/first.py")           # dans changes (1er)
        + _mod_diff("tests/test_alpha.py")    # test corrigé
    )
    recap = {
        "symptoms": "s", "explanation": "e", "tests": "t",
        "changes": [
            {"file": "src/first.py", "summary": "1"},
            {"file": "src/second.py", "summary": "2"},
        ],
    }
    payload = build_recap_payload(recap, diff)
    assert payload["recap_missing"] is False
    files = [d["file"] for d in payload["diffs"]]
    sections = [d["section"] for d in payload["diffs"]]
    # changes dans l'ordre de recap → other → tests (neufs puis corrigés).
    assert files == [
        "src/first.py", "src/second.py",     # section changes, ordre recap
        "src/orphan.py",                     # section other
        "tests/test_beta.py",                # test neuf
        "tests/test_alpha.py",               # test corrigé
    ]
    assert sections == ["changes", "changes", "other", "tests", "tests"]


def test_tests_isolated_even_when_listed_in_changes():
    # Un test_*.py cité dans recap.changes reste isolé en section tests.
    diff = _mod_diff("src/x.py") + _mod_diff("tests/test_x.py")
    recap = {"changes": [{"file": "src/x.py"}, {"file": "tests/test_x.py"}]}
    payload = build_recap_payload(recap, diff)
    assert [(d["file"], d["section"]) for d in payload["diffs"]] == [
        ("src/x.py", "changes"),
        ("tests/test_x.py", "tests"),
    ]


def test_fallback_when_recap_missing_sorts_alpha_all_section():
    diff = _mod_diff("src/zeta.py") + _mod_diff("src/alpha.py") + _mod_diff("tests/test_m.py")
    payload = build_recap_payload(None, diff)
    assert payload["recap_missing"] is True
    assert payload["recap"] is None
    files = [d["file"] for d in payload["diffs"]]
    sections = [d["section"] for d in payload["diffs"]]
    assert files == ["src/alpha.py", "src/zeta.py", "tests/test_m.py"]
    assert sections == ["all", "all", "all"]


def test_fallback_when_recap_empty_dict():
    diff = _mod_diff("src/a.py")
    payload = build_recap_payload({}, diff)
    assert payload["recap_missing"] is True
    assert payload["diffs"][0]["section"] == "all"


def test_no_diff_yields_empty_diffs():
    recap = {"changes": [{"file": "src/a.py"}]}
    payload = build_recap_payload(recap, "")
    assert payload["diffs"] == []
    assert payload["recap_missing"] is False
