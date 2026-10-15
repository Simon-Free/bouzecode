"""Front-end assets are testmon's blind spot — RunPythonTest must cover it itself.

Measured on 2026-09-08 in this repo: with `--testmon`, editing a template gives
`testmon: changed files: 0` and the test is NOT rerun, while editing the .py that
reads it does rerun it. testmon selects through coverage.py, which sees PYTHON
only: a changed .css/.js/.html never even enters its dependency graph.

Playwright, on the other hand, executes the real JS and applies the real CSS —
that is the whole reason `src/bouzecode/web_v2/tests/playwright/` exists (its
conftest says a test only lands there when the behaviour is INVISIBLE to the
Flask test client: computed CSS, pixel geometry, real clicks).

So the gap is not the execution, it is the TRIGGER. These helpers are that
trigger: when git says a front asset moved, the Playwright folders are added to
the run, no browser coverage and no second database involved.
"""

from pathlib import Path

from bouzecode.backend.tools.ops.test_runner import (
    _changed_front_targets,
    _is_front_asset,
    _playwright_test_dirs,
)

REPO = Path(__file__).resolve().parents[4]


class TestIsFrontAsset:
    def test_css_and_js_under_static_are_front_assets(self):
        assert _is_front_asset("src/bouzecode/web_v2/static/js/lignes.js")
        assert _is_front_asset("src/bouzecode/web_v2/static/css/app.css")

    def test_html_under_templates_is_a_front_asset(self):
        assert _is_front_asset("src/bouzecode/web_v2/templates/bureau.html")

    def test_windows_backslashes_are_understood_too(self):
        assert _is_front_asset(r"src\bouzecode\web_v2\static\js\lignes.js")

    def test_python_is_not_a_front_asset_because_testmon_already_covers_it(self):
        assert not _is_front_asset("src/bouzecode/backend/tools/ops/test_runner.py")

    def test_js_outside_static_is_ignored(self):
        # node tooling, configs, vendored scripts: not the app's front-end.
        assert not _is_front_asset("scripts/build/rollup.config.js")

    def test_html_outside_templates_is_ignored(self):
        assert not _is_front_asset("docs/report.html")


class TestPlaywrightTestDirs:
    def test_it_finds_the_real_playwright_folder_of_this_repo(self):
        # It lives under src/, OUTSIDE pyproject's testpaths=["tests"], which is
        # exactly why it cannot be hardcoded as tests/playwright.
        dirs = _playwright_test_dirs(REPO)
        assert "src/bouzecode/web_v2/tests/playwright" in dirs

    def test_paths_are_relative_so_they_can_be_appended_to_the_command(self):
        for d in _playwright_test_dirs(REPO):
            assert not Path(d).is_absolute()
            assert "\\" not in d  # posix separators, as pytest targets

    def test_a_playwright_folder_without_conftest_is_not_a_test_folder(self, tmp_path):
        (tmp_path / "vendor" / "playwright").mkdir(parents=True)
        assert _playwright_test_dirs(tmp_path) == []


class TestChangedFrontTargets:
    def test_no_git_no_crash_and_no_targets(self, tmp_path):
        # A test runner must never blow up because git is missing or the folder
        # is not a repository.
        assert _changed_front_targets(tmp_path) == []

    def test_this_repo_answers_without_raising(self):
        # Whatever the working tree currently holds, the call is safe and returns
        # a list of relative paths.
        out = _changed_front_targets(REPO)
        assert isinstance(out, list)
        for d in out:
            assert not Path(d).is_absolute()
