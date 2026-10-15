# [desc] RunPythonTest tool: runs pytest via uv with auto env loading, parallel support, and project detection [/desc]
"""RunPythonTest tool implementation."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from ...testd.common import sans_fenetre
from .progression_terminal import LigneProgression
from .python_du_projet import module_absent, venv_du_depot_principal  # noqa: F401 (API)
from .python_du_projet import python_du_projet as _python_without_uv
from .python_du_projet import venv_a_pytest as _venv_has_pytest
from .runner_guards import (
    DEFAULT_PARALLEL,
    caller_chose_durations,
    full_suite_refusal,
    show_views,
    with_default_durations,
    with_safe_defaults,
    xdist_args,
)


#  Sources du plugin (sans proxy, branche sur le navigateur chaud de testd, sinon coquille headless
#  tuée à la fermeture) : deux vrais modules, copiés dans un dossier temporaire à chaque run.
_DOSSIER_PLUGIN = Path(__file__).resolve().parents[2] / "testd" / "plugin"
_PLAYWRIGHT_PLUGIN = {nom: (_DOSSIER_PLUGIN / nom).read_text(encoding="utf-8")
                      for nom in ("_bz_pw_patch.py", "_bz_pw_lancement.py")}


def _inject_playwright_plugin(env: dict, cmd_parts: list) -> str | None:
    """Inject a pytest plugin that auto-configures Playwright for corporate env.

    Returns tmpdir path (caller cleans up) or None if injection skipped.
    """
    tmpdir = tempfile.mkdtemp(prefix="bz_pw_")
    for nom, source in _PLAYWRIGHT_PLUGIN.items():
        (Path(tmpdir) / nom).write_text(source, encoding="utf-8")
    existing = env.get("PYTHONPATH", "")
    sep = ";" if sys.platform == "win32" else ":"
    env["PYTHONPATH"] = f"{tmpdir}{sep}{existing}" if existing else tmpdir
    cmd_parts.extend(["-p", "_bz_pw_patch"])
    return tmpdir

_COLLECTED_RE = re.compile(r'collected (\d+) items?')
_XDIST_COLLECTED_RE = re.compile(r'\d+ workers? \[(\d+) items?\]')
_XDIST_RESULT_RE = re.compile(r'^\[gw\d+\]\s+(PASSED|FAILED|SKIPPED|ERROR)\s+')
_STANDARD_RESULT_RE = re.compile(r' (PASSED|FAILED|SKIPPED|ERROR)\b')


# A sub-agent prints one line per update in its tab: once a second is live enough.
_PROGRESS_PERIOD_S = 1.0


def _progress_text(done: int, total: int, passed: int, failed: int, skipped: int) -> str:
    return f"pytest: {done}/{total} , ✅{passed} ❌{failed} ⏭{skipped}"


def _stream_with_progress(proc, timeout: int, progression=None) -> tuple[list[str], bool]:
    """Read proc stdout line-by-line and report the live progress (`pytest: n/N ...`).

    `progression` (callable(str)) is where the progress goes. A sub-agent passes its own
    channel (it runs in a thread of the main process: a write to the shared terminal would
    land in the MAIN agent's view). None = the main agent: `LigneProgression`, i.e. the
    spinner's live line in the TUI, else a CR-rewritten line on stderr.

    Returns (all_lines, timed_out).
    """
    terminal = None
    if progression is None:
        terminal = progression = LigneProgression()
    lines: list[str] = []
    timed_out = False
    total = None
    done = 0
    passed = 0
    failed = 0
    skipped = 0
    last_report = time.monotonic()

    def _kill_on_timeout():
        nonlocal timed_out
        timed_out = True
        _kill_proc_tree(proc.pid)

    timer = threading.Timer(timeout, _kill_on_timeout)
    timer.start()

    try:
        for raw_line in proc.stdout:
            line = raw_line.rstrip('\n\r')
            lines.append(line)

            # Detect total collected
            if total is None:
                m = _COLLECTED_RE.search(line) or _XDIST_COLLECTED_RE.search(line)
                if m:
                    total = int(m.group(1))
                    progression(_progress_text(0, total, 0, 0, 0))
                    last_report = time.monotonic()
                    continue

            # Detect individual test results
            m = _XDIST_RESULT_RE.match(line) or _STANDARD_RESULT_RE.search(line)
            if m:
                status = m.group(1)
                done += 1
                if status == "PASSED":
                    passed += 1
                elif status == "FAILED":
                    failed += 1
                elif status == "SKIPPED":
                    skipped += 1
                if time.monotonic() - last_report >= _PROGRESS_PERIOD_S:
                    progression(_progress_text(done, total or done, passed, failed, skipped))
                    last_report = time.monotonic()

        # stderr merged into stdout via subprocess.STDOUT — no separate read needed

        proc.wait()
    finally:
        timer.cancel()
        if total or done:
            progression(_progress_text(done, total or done, passed, failed, skipped))
        if terminal is not None:
            terminal.fermer()

    return lines, timed_out


def _find_project_root(target: str | None = None) -> Path:
    """Walk up from target (or cwd) to find the nearest pyproject.toml."""
    from ...core.dossier_agent import courant, resoudre  # sous-agent isole : SON dossier
    start = Path(resoudre(target)).resolve() if target else Path(courant())
    if start.is_file():
        start = start.parent
    for folder in [start, *start.parents]:
        if (folder / "pyproject.toml").exists():
            return folder
    return Path(courant())


def _load_env_file(env_path: Path, env: dict[str, str]) -> dict[str, str]:
    """Parse a .env file and merge into env dict (existing keys NOT overwritten)."""
    if not env_path.exists():
        return env
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        env.setdefault(key, value)
    return env


def _get_base_env(dossier: str = "") -> dict[str, str]:
    """Env for the pytest subprocess, without an inherited PYTHONHOME.

    Its venv is the one of the project at `dossier` (the project under test; default: the
    agent's folder) - rule of 2026-10-12, see venv_du_projet.

    See shell_env.strip_inherited_python_home: a leaked PYTHONHOME (uv/IDE)
    breaks every python launched from PATH with `SRE module mismatch`.
    """
    from .shell_env import strip_inherited_python_home, worktree_child_env
    from ...core.dossier_agent import courant
    return worktree_child_env(strip_inherited_python_home(_get_base_env_raw()),
                              dossier=dossier or courant())


def _get_base_env_raw() -> dict[str, str]:
    """Get environment with user-level vars (Windows registry merge)."""
    from ...core.dossier_agent import environ  # + variables du sous-agent (venv, worktree)
    env = environ()
    try:
        if sys.platform != "win32":
            return env
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                    env.setdefault(name, value)
                    i += 1
                except OSError:
                    break
    except Exception:
        pass
    return env


def _kill_proc_tree(pid: int) -> None:
    """Kill process tree (Windows & Unix)."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **sans_fenetre(),
            )
        else:
            import signal
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        pass


_MISSING_PYTEST_MARKERS = (
    "No module named '_pytest'",
    "No module named _pytest",
    "No module named 'pytest'",
    "No module named pytest",
)


def _looks_like_missing_pytest(output: str) -> bool:
    """True when the run died because pytest is absent from the resolved env.

    Typical on a venv SHARED with the server: `Scripts/pytest.exe` survives an
    old install while the module is gone, so uv resolves the shim and the shim
    crashes on `import _pytest`.

    Guard: if pytest printed its own session banner, pytest obviously exists and
    the marker belongs to the code under test — never retry in that case.
    """
    if "test session starts" in output:
        return False
    return any(marker in output for marker in _MISSING_PYTEST_MARKERS)


def _with_pytest_overlay(cmd_parts: list[str]) -> list[str]:
    """Same command, plus an ephemeral uv overlay that provides pytest.

    `uv run --with pytest` materialises pytest in the uv CACHE, layered on top of
    the project environment: the project venv is never written to. That is what
    makes this fallback safe when the venv is shared with the server and other
    agents — a `uv sync --extra test` would rewrite that shared venv instead.
    """
    if "pytest" in _overlay_packages(cmd_parts):
        return list(cmd_parts)
    out = list(cmd_parts)
    at = 2 if out[:2] == ["uv", "run"] else 0
    for pkg in ("pytest-xdist", "pytest"):
        out[at:at] = ["--with", pkg]
    return out


def _overlay_packages(cmd_parts: list[str]) -> set[str]:
    """Packages already provided through `uv run --with <pkg>` overlays.

    Compared by EXACT value, never by substring: "pytest" is a substring of
    "pytest-testmon", so a substring check would make the missing-pytest
    fallback believe pytest was already there in testmon mode.
    """
    return {
        cmd_parts[i + 1]
        for i, arg in enumerate(cmd_parts[:-1])
        if arg == "--with"
    }


def _is_front_asset(path: str) -> bool:
    """True for the three file families testmon is structurally blind to.

    Measured: editing a template/.css/.js does not even make testmon list it in
    `changed files` (its graph comes from coverage.py, which traces Python only).
    So the browser tests that exist PRECISELY to assert computed CSS, real JS
    execution and pixel geometry are never rescheduled by testmon.
    """
    p = path.replace("\\", "/")
    segments = p.split("/")
    suffix = p.rsplit(".", 1)[-1].lower() if "." in p else ""
    if suffix in {"css", "js"} and "static" in segments:
        return True
    if suffix in {"html", "jinja", "jinja2"} and "templates" in segments:
        return True
    return False


def _playwright_test_dirs(project_root: Path) -> list[str]:
    """Directories holding browser tests, as paths relative to project_root.

    Scanned, never hardcoded: bouzecode keeps them under `src/` (outside
    `testpaths = ["tests"]`), so a plain `pytest` run never even collects them.
    A directory qualifies when it is named `playwright` AND carries a conftest.
    """
    found: list[str] = []
    for base in ("src", "tests"):
        root = project_root / base
        if not root.is_dir():
            continue
        for candidate in root.rglob("playwright"):
            if candidate.is_dir() and (candidate / "conftest.py").is_file():
                found.append(candidate.relative_to(project_root).as_posix())
    return sorted(set(found))


def _changed_front_targets(project_root: Path) -> list[str]:
    """Browser-test dirs to append when git says a front asset changed.

    Fail-safe by construction: no git, git error, no changed asset or no
    playwright directory all return [] — a test runner must never blow up
    because git is missing.
    """
    try:
        changed: list[str] = []
        for args in (
            ["git", "diff", "--name-only", "HEAD"],
            ["git", "ls-files", "--others", "--exclude-standard"],
        ):
            proc = subprocess.run(
                args,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                **sans_fenetre(),
            )
            if proc.returncode == 0:
                changed.extend(line.strip() for line in proc.stdout.splitlines())
        if not any(_is_front_asset(c) for c in changed if c):
            return []
        return _playwright_test_dirs(project_root)
    except Exception:
        return []


def _retirer_venv_fantome(project_root: Path, existait: bool) -> str:
    """Retire le `.venv` qu'un `uv run` vient de fabriquer SANS pytest, et le dit.

    Mesuré sur le poste Windows, worktrees d'agents : « Creating virtual environment at:
    .venv » puis « Failed to spawn: `pytest` ». Ce venv vide devient le plus proche et masque
    le venv de base pour tout le reste de la session. Un `.venv` qui existait avant l'appel
    n'est JAMAIS touché."""
    venv = project_root / ".venv"
    if existait or not venv.exists() or _venv_has_pytest(venv):
        return ""
    shutil.rmtree(venv, ignore_errors=True)
    return (f"[RunPythonTest] `uv run` avait créé un .venv VIDE dans {project_root} : retiré "
            f"(il aurait masqué le venv de base). Lance les tests avec le python du venv de "
            f"base (PYTHONPATH=<projet>/src) ou Environment(action='venv').\n")


def _python_of_run(cmd_parts: list[str], project_root: Path) -> str | None:
    """L'interpréteur qui exécutera pytest : celui de la commande directe, sinon celui du
    `.venv` du projet (ce que `uv run --directory` résout). None : aucun venv sur disque."""
    if cmd_parts[:1] != ["uv"]:
        return cmd_parts[0]
    venv = project_root / ".venv"
    exe = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    return str(exe) if exe.exists() else None


def _ensure_xdist(cmd_parts: list[str], project_root: Path, env: dict) -> tuple[list[str], str]:
    """`-n` demandé : pytest-xdist doit être importable là où pytest tourne.

    Sans lui pytest meurt sur « unrecognized arguments: -n » (T37 du rapport
    docs/reduction_tokens). Sans venv (`uv run`), un overlay éphémère le fournit. Dans un venv
    EXISTANT, rien n'est installé (cf. `python_du_projet`) : l'absence est dite, avec le
    remède. Rend (commande, note) ; lève RuntimeError (rendue en « Error: » par l'appelant)."""
    if "-n" not in cmd_parts:
        return cmd_parts, ""
    if cmd_parts[:1] == ["uv"]:
        if "pytest-xdist" in _overlay_packages(cmd_parts):
            return cmd_parts, ""
        return cmd_parts[:2] + ["--with", "pytest-xdist"] + cmd_parts[2:], ""
    if module_absent(cmd_parts[0], "xdist", env):
        raise RuntimeError(f"pytest-xdist absent de {cmd_parts[0]} ; il n'y est pas installé (un "
                           f"venv existant n'est jamais modifié). Relance avec parallel='off'.")
    return cmd_parts, ""


def _with_testmon_overlay(cmd_parts: list[str]) -> list[str]:
    """Same command, plus an ephemeral uv overlay providing pytest-testmon.

    Same rationale as `_with_pytest_overlay`: the plugin is materialised in the
    uv CACHE, so the project venv — shared with the server and every other
    agent — is never written to. testmon stays an opt-in measuring tool, not a
    project dependency.
    """
    if "pytest-testmon" in _overlay_packages(cmd_parts):
        return list(cmd_parts)
    out = list(cmd_parts)
    at = 2 if out[:2] == ["uv", "run"] else 0
    out[at:at] = ["--with", "pytest-testmon"]
    return out


def _missing_pytest_help(project_root: Path, cmd_str: str, output: str) -> str:
    """Actionable message when pytest is missing: an existing venv is never completed, and
    without a venv even the uv overlay could not provide it."""
    tail = "\n".join(output.strip().splitlines()[-15:])
    return (
        "Error: pytest is not importable in the resolved environment. An existing venv is\n"
        "never modified; without a venv, the `uv run --with pytest` overlay failed too.\n"
        f"Command attempted: {cmd_str}\n"
        f"Project root: {project_root}\n"
        "\n"
        "Why: pytest lives in [project.optional-dependencies].test, which is not\n"
        "installed in the resolved venv (a leftover Scripts/pytest.exe shim can make\n"
        "it look installed while the module is gone).\n"
        "\n"
        "Fallback path, in order:\n"
        "  1. Check the uv cache is reachable, then retry (the overlay needs to\n"
        "     download pytest once).\n"
        "  2. Use a THROWAWAY venv, never the shared one:\n"
        f"       uv venv --python 3.12 {project_root / '.venv-test'}\n"
        f"       uv pip install --python {project_root / '.venv-test' / 'Scripts' / 'python.exe'} pytest pytest-xdist\n"
        f"       set PYTHONPATH={project_root / 'src'} and run `-m pytest` with that interpreter.\n"
        "\n"
        "NEVER run `uv sync` here: the venv is shared with the server and other\n"
        "agents — uv deletes and recreates it, which kills every running agent.\n"
        "\n"
        f"Last output lines:\n{tail}"
    )


# ── Sélection par défaut et comparaison avec la base (cf. impacted.py, baseline.py) ──────

def _selection_par_defaut(extra_args: list[str]):
    """Sans cible ni filtre : les tests impactés par la branche. Rend (sélection, cibles
    absolues, extra_args + `--deselect` des tests lents)."""
    from .impacted import selection_impactee
    racine = _find_project_root(None)
    selection = selection_impactee(racine)
    deselect = [arg for chemin in selection.deselect for arg in ("--deselect", chemin)]
    return selection, [str(racine / c) for c in selection.cibles], extra_args + deselect


def _args_communs_base(marker: str | None) -> list[str]:
    """Arguments du rejeu sur la base, hors xdist (le démon y met le `-n` qu'il a accordé)."""
    return [*(["-m", marker] if marker else []), "-p", "_bz_pw_patch"]


def _comparaison_base(project_root: Path, issues_json: Path, cmd_parts: list[str], env: dict,
                      xdist: list[str], marker: str | None, timeout: int) -> str:
    """Les ids en échec ou en erreur de ce run, rejoués sur le merge-base (NEW vs pre-existing)."""
    from .baseline import comparer_avec_la_base
    from .selection_plugin import lire_issues
    echecs = sorted(i for i, issue in lire_issues(issues_json).items() if issue in ("failed", "error"))
    return comparer_avec_la_base(project_root, echecs, _python_of_run(cmd_parts, project_root),
                                 env, [*xdist, *_args_communs_base(marker)], timeout)


def _via_testd(cmd_parts, env, project_root, timeout, wait, progression, views, entete, **job):
    """Le run passe par la file du démon de tests de la machine (cf. bouzecode.backend.testd) ;
    `job` : cibles, base, a_nettoyer (cf. testd.client.soumettre)."""
    from ...testd.rendu import via_testd
    return via_testd(cmd_parts, env, project_root, _python_of_run(cmd_parts, project_root),
                     timeout, wait, progression, views, entete, **job)


def run_python_test(
    targets: list[str] | None = None,
    parallel: str = DEFAULT_PARALLEL,
    marker: str | None = None,
    keyword: str | None = None,
    timeout: int = 300,
    no_sync: bool = False,
    extra_args: list[str] | None = None,
    testmon: bool = False,
    full: bool = False,
    show: list[str] | str | None = None,
    progression=None,
    wait: bool = True,
) -> str:
    """Execute pytest via uv with proper env loading.

    Garde-fous (cf. `runner_guards`) : `-n auto` refusé, `full=True` réservé au nightly
    (`BZ_NIGHTLY=1`), `--durations` ajouté pour montrer où part le temps. Le résultat ne garde que
    le strict utile (cf. `pytest_compact`) ; `show` élargit."""
    xdist, refusal = xdist_args(parallel, extra_args)
    views, show_refusal = show_views(show)
    refusal = refusal or show_refusal or full_suite_refusal(full)
    if refusal:
        return refusal
    if caller_chose_durations(extra_args):
        views += ("durations",)
    extra_args = with_safe_defaults(with_default_durations(extra_args, views))
    if targets:  # une seule résolution, depuis le dossier de l'agent (cf. cibles_pytest)
        from .cibles_pytest import cibles_absolues
        targets, introuvable = cibles_absolues(targets)
        if introuvable:
            return introuvable
    selection = None
    if not (targets or marker or keyword or testmon or full):
        selection, targets, extra_args = _selection_par_defaut(extra_args)
        if not targets:
            return selection.ligne

    # testmon selects tests from a coverage-derived dependency DB, and pytest
    # DISABLES that selection as soon as -m is used ("selection automatically
    # deactivated because -m was used"). Silently ignoring `marker` would cost
    # the coverage overhead (+34% measured) for ZERO selection gain, so fail
    # loudly instead of shipping a decorative option.
    if testmon and marker:
        return (
            "Error: testmon=True is incompatible with marker "
            f"(-m {marker!r}): pytest deactivates testmon selection whenever -m "
            "is used, so the run would pay the coverage overhead and select "
            "nothing.\nNarrow the run with `targets` instead of `marker`."
        )

    # Determine project root from first target or cwd
    first_target = targets[0] if targets else None
    project_root = _find_project_root(first_target)

    # Build environment
    env = _get_base_env(str(project_root))
    _load_env_file(project_root / ".env", env)

    # Build pytest command. Un venv EXISTANT n'est jamais synchronisé ni modifié : son python
    # est exécuté directement (cf. `python_du_projet`). `PYTHONPATH` en tête garantit que c'est
    # le code de CE worktree qui est importé, avant les `.pth` d'editable install. `uv run`
    # n'est que le repli sans aucun venv, et toujours `--no-sync` (`no_sync` n'a plus d'effet).
    direct = _python_without_uv(project_root, env)
    if direct and testmon and module_absent(direct, "testmon", env):
        return (f"Error: pytest-testmon absent de {direct} ; il n'y est pas installé (un venv "
                "existant n'est jamais modifié). Relance sans testmon.")
    if direct:
        cmd_parts = [direct, "-m", "pytest"]
        src = project_root / "src"
        if src.is_dir():
            precedent = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = (
                str(src) + os.pathsep + precedent if precedent else str(src)
            )
    else:
        cmd_parts = ["uv", "run", "--no-sync", "--directory", str(project_root), "pytest"]

    # Parallel option (bounded worker count, validated above)
    cmd_parts.extend(xdist)

    # Always verbose
    cmd_parts.append("-v")

    # testmon: run ONLY the tests affected by changed code. `-o addopts=` wipes
    # the project's own addopts, which on this repo carries a permanent
    # `-m 'not web and not ui'` that would deactivate the selection entirely.
    if testmon:
        cmd_parts.extend(["--testmon", "-o", "addopts="])

    # Marker filter
    if marker:
        cmd_parts.extend(["-m", marker])

    # Keyword filter
    if keyword:
        cmd_parts.extend(["-k", keyword])

    # Extra args
    if extra_args:
        cmd_parts.extend(extra_args)

    # Targets (files/dirs)
    if targets:
        hors_projet = []
        for t in targets:
            # Make paths relative to project_root if they're absolute
            p = Path(t)
            if p.is_absolute():
                try:
                    rel = p.relative_to(project_root)
                    cmd_parts.append(str(rel))
                except ValueError:
                    cmd_parts.append(str(p))
                    hors_projet.append(p if p.is_dir() else p.parent)
            else:
                cmd_parts.append(t)
        #  Cible hors du projet (sonde dans %TEMP%) : sans rootdir à elle, pytest construit ses
        #  collecteurs depuis la RACINE du disque et parcourt %TEMP% entier, où d'autres process
        #  créent et suppriment des dossiers (FileNotFoundError « collecting test session »).
        if hors_projet and "--rootdir" not in cmd_parts:
            cmd_parts += ["--rootdir", os.path.commonpath([str(d) for d in hors_projet])]

    # testmon is blind to front assets: a changed template/.css/.js is not even
    # listed among its `changed files` (its graph comes from coverage.py, which
    # traces Python only). The browser tests exist PRECISELY to assert computed
    # CSS, real JS execution and pixel geometry, so testmon would never
    # reschedule them. Add them back ourselves when git says an asset moved.
    front_note = ""
    if testmon:
        extra_dirs = [
            d for d in _changed_front_targets(project_root) if d not in cmd_parts
        ]
        if extra_dirs:
            cmd_parts.extend(extra_dirs)
            front_note = (
                "[RunPythonTest] front assets changed -> added "
                + ", ".join(extra_dirs)
                + " (testmon cannot see .css/.js/.html)\n"
            )

    # Sans venv seulement : testmon vient d'un overlay uv éphémère.
    # Done BEFORE _inject_playwright_plugin, which mutates cmd_parts in place.
    if testmon and not direct:
        cmd_parts = _with_testmon_overlay(cmd_parts)

    # Inject Playwright plugin for system browser + proxy bypass
    pw_tmpdir = _inject_playwright_plugin(env, cmd_parts)
    # Sélection par ids (testmon) et issue de chaque test, pour la comparaison avec la base.
    from .selection_plugin import injecter_selection, nettoyer
    sel_tmpdir, issues_json = injecter_selection(
        env, cmd_parts, *((selection.ids, selection.fichiers_filtres) if selection else ()))

    # Force unbuffered output so the progress updates in real time
    env["PYTHONUNBUFFERED"] = "1"
    # Sortie lue en UTF-8 : sans ça, un pipe Windows est en cp1252 et « refusée » arrive en « refus�e ».
    env.setdefault("PYTHONIOENCODING", "utf-8")

    # Execute with live progress bar
    kwargs = dict(
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(project_root),
        env=env,
    )
    if sys.platform != "win32":
        kwargs["start_new_session"] = True
    kwargs.update(sans_fenetre())  # aucune console visible pour pytest et ses enfants

    cmd_str = " ".join(cmd_parts)

    venv_existait = (project_root / ".venv").exists()

    def _launch(parts: list[str]) -> tuple[str, bool]:
        proc = subprocess.Popen(parts, **kwargs)
        lines, timed_out = _stream_with_progress(proc, timeout, progression)
        out = "\n".join(lines)
        if parts[:1] == ["uv"]:
            out = _retirer_venv_fantome(project_root, venv_existait) + out
        return out, timed_out

    try:
        cmd_parts, xdist_note = _ensure_xdist(cmd_parts, project_root, env)
        cmd_str = " ".join(cmd_parts)
        #  Sélection, défauts et plugin d'issues sont déjà dans la commande et l'env : le démon
        #  les exécute tels quels ; la comparaison avec la base tourne dans le créneau du job.
        via_daemon = _via_testd(
            cmd_parts, env, project_root, timeout, wait, progression, views,
            (selection.ligne + "\n" if selection else "") + f"{xdist_note}{front_note}",
            cibles=targets or [], a_nettoyer=[sel_tmpdir],
            base={"communs": _args_communs_base(marker)} if selection or full else None)
        if via_daemon is not None:
            if not wait:
                sel_tmpdir = None  # confié au démon, qui le supprime en fin de job
            return via_daemon
        out, timed_out = _launch(cmd_parts)

        if timed_out:
            return f"Error: tests timed out after {timeout}s (process killed)\nCommand: {cmd_str}"

        # pytest missing from the resolved env: retry ONCE through an ephemeral
        # uv overlay instead of failing with a raw traceback the agent cannot act on.
        if _looks_like_missing_pytest(out):
            #  Overlay `--with pytest` : seulement sans venv (`uv run`) ; un venv existant
            #  n'est jamais complété.
            fallback = _with_pytest_overlay(cmd_parts) if cmd_parts[:1] == ["uv"] else cmd_parts
            if fallback == cmd_parts:
                return _missing_pytest_help(project_root, cmd_str, out)
            retry, timed_out = _launch(fallback)
            fallback_str = " ".join(fallback)
            if timed_out:
                return (
                    f"Error: tests timed out after {timeout}s (process killed)\n"
                    f"Command: {fallback_str}"
                )
            if _looks_like_missing_pytest(retry):
                return _missing_pytest_help(project_root, fallback_str, retry)
            out, cmd_str = retry, fallback_str

        result = out.strip() or "(no output)"
        header = (f"{xdist_note}{front_note}[RunPythonTest] cwd={project_root}\n"
                  f"$ {cmd_str}\n{'─' * 60}\n")
        if selection or full:
            header = (selection.ligne + "\n" if selection else "") + header + _comparaison_base(
                project_root, issues_json, cmd_parts, env, xdist, marker, timeout)
        from .pytest_zero import aucun_test_lance, explication
        if aucun_test_lance(result):  # le dire, avec la cause et le remède (cf. pytest_zero)
            header += explication(cmd_parts, project_root, env, result)
        # Échecs d'abord, rien d'autre sur un run vert (cf. pytest_compact).
        from .pytest_compact import rendu_pytest
        return header + rendu_pytest(result, views, toujours_sauver=True)

    except FileNotFoundError:
        return (
            f"Error: 'uv' not found. Ensure uv is installed and in PATH.\n"
            f"Command attempted: {cmd_str}"
        )
    except Exception as e:
        return f"Error: {e}\nCommand: {cmd_str}"
    finally:
        nettoyer(sel_tmpdir)
