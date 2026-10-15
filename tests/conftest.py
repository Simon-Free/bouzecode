# [desc] Pytest autouse fixtures: load bouzecode/.env so real-API tests always have credentials. [/desc]
"""Load bouzecode/.env at test collection time.

Tests that hit the real internal LLM gateway API require `ANTHROPIC_API_KEY`,
`ANTHROPIC_BASE_URL`, and the corporate proxy/SSL settings to be in the process
env. We load `bouzecode/.env` once here so any developer running `pytest`
gets the same setup as `bouzeui.ps1`.
"""
from __future__ import annotations

import functools
import os
from pathlib import Path

import pytest

# Fixture de session : dépôt git modèle construit une fois par worker, copié par test.
from tests.git_modeles import depot_modele  # noqa: F401
# Un test bouzecode() en échec affiche la transcription de sa conversation simulée.
from tests.harness_transcript import pytest_runtest_makereport, pytest_runtest_setup  # noqa: F401


def _load_env_file(env_path: Path) -> None:
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_BOUZECODE_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _BOUZECODE_ROOT / ".env"

# Web tests (Playwright) are set aside by marker, but pytest still IMPORTS their
# modules at collection — without playwright installed every file errors out.
# Skip collecting them entirely in that case.
import importlib.util
if importlib.util.find_spec("playwright") is None:
    collect_ignore_glob = ["frontend/*", "frontend/**/*"]
if _ENV_FILE.exists():
    _load_env_file(_ENV_FILE)

if "ANTHROPIC_AUTH_TOKEN" in os.environ and "ANTHROPIC_API_KEY" not in os.environ:
    os.environ["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_AUTH_TOKEN"]

# PYTHONHTTPSVERIFY n'est plus lu par les backends (vérification TLS toujours
# active, cf. core/tls.py) ; on ne le pose plus pour ne pas masquer une régression.

# The web_v2 completion poller (wake.start_poller) spawns a daemon thread that
# would tick() against the developer's real ~/.bouzecode tickets whenever a test
# builds the Flask app — potentially spawning real agents. Off by default in tests.
os.environ.setdefault("BOUZECODE_DISABLE_WAKE_POLLER", "1")
# ⚠ La ligne ci-dessus N'A JAMAIS RIEN COUPÉ : `wake.start_poller` lit `BOUZECODE_WAKE_POLLER`
# == "0", pas `BOUZECODE_DISABLE_WAKE_POLLER`. Le garde-fou portait un nom que personne ne lit.
# Conséquence mesurée : `create_app()` (app.py:141) armait un thread démon qui rejoue `tick()`
# toutes les N secondes — donc APRÈS les teardowns qui rendent `AGENTS_DIR` au parc RÉEL. D'où
# des `kill_agent` asynchrones sur de vrais agents, inattribuables à un test précis.
os.environ.setdefault("BOUZECODE_WAKE_POLLER", "0")


# RunPythonTest fixture-target files: collectable by an explicit `pytest <path>`
# (the runner spawns exactly that) but excluded from the main suite —
# test_trivial_runner_slow sleeps 30s and is only meant to be a subprocess target.
collect_ignore = [
    "backend/tools/runner/test_trivial_runner.py",
    "backend/tools/runner/test_trivial_runner_slow.py",
    # ⚠ Les DEUX lignes ci-dessus ne visaient que les copies du dossier runner. Les cibles
    # réellement utilisées par les tests e2e vivent à la RACINE de `tests/`, et elles étaient
    # donc bel et bien collectées par la suite principale : mesure du 2026-09-29,
    # `test_trivial_runner_slow.py::test_slow_operation` = 30 s de `time.sleep` payées à chaque
    # run complet, pour un fichier qui n'est qu'un ARTEFACT destiné à être lancé en
    # sous-process. `collect_ignore` ignore un dossier parcouru, pas un chemin passé
    # explicitement : `pytest tests/test_trivial_runner_slow.py` (ce que fait RunPythonTest)
    # continue de le collecter.
    "test_trivial_runner.py",
    "test_trivial_runner_slow.py",
]


def pytest_configure(config):
    config.addinivalue_line("markers", "backend: agent-engine tests (tests/backend/)")
    config.addinivalue_line("markers", "ui: terminal-UI tests (tests/ui/)")
    config.addinivalue_line("markers", "web: Flask + Playwright web tests (tests/frontend/)")
    # `slow` a DEUX usages, compatibles. Ici, le fichier-cible `test_trivial_runner_slow.py`
    # le porte a la main : le RunPythonTest e2e le selectionne par `-m slow` pour prouver le
    # filtrage par marqueur. Ailleurs dans la suite, il est DERIVE (cf. tests/auto_markers.py)
    # et signifie « plus de 5 s constatees ». Rien a arbitrer : le fichier-cible est de toute
    # facon exclu du run principal par `collect_ignore` ci-dessus.
    config.addinivalue_line("markers", "slow: plus de 5 s constatees (derive) ; aussi le "
                                       "marqueur du fichier-cible de RunPythonTest")
    config.addinivalue_line("markers", "network: sort du process — vrai gateway LLM")
    config.addinivalue_line("markers", "timing: chevauchements temporels — ne pas paralleliser")


def pytest_collection_modifyitems(config, items):
    """Pose les DEUX axes de marqueurs, tous deux derives (cf. `tests/auto_markers.py`).

    Axe zone : `backend` / `ui` / `web`, d'apres le dossier — sans quoi l'`addopts`
    `-m 'not web and not ui'` de pyproject.toml ne desselectionne RIEN.
    Axe dependance : `network` / `llm` / `timing` / `slow`, d'apres la cloture de fixtures
    du test et son corps.

    ⛔ Ce module definissait ce hook DEUX fois (l'un ici, l'autre en tete de fichier) : Python
    ne garde que le dernier, et pytest n'a donc jamais vu le premier. Un axe branche dans la
    mauvaise copie serait mort en silence. Une seule definition desormais.
    """
    from tests.auto_markers import (
        marker_for, markers_for, markers_for_module, markers_for_source,
        source_du_module, source_du_test,
    )

    sources_de_modules: dict[str, str] = {}
    for item in items:
        chemin = str(item.fspath)
        zone = marker_for(chemin)
        if zone:
            item.add_marker(zone)
        marqueurs = markers_for(chemin, item.fixturenames)
        marqueurs |= markers_for_source(source_du_test(item))
        marqueurs |= markers_for_module(source_du_module(chemin, sources_de_modules))
        for marqueur in marqueurs:
            item.add_marker(marqueur)


@pytest.fixture(autouse=True)
def _llm_network_guard(monkeypatch):
    """Hermetic guard: a test reaches the live gateway ONLY after calling
    require_api_key() (which itself skips when credentials are absent). Any other
    test that hits stream_anthropic fails loudly instead of calling prod, so the
    suite never makes an accidental real LLM call."""
    from tests import cache_conversation_helpers as cch
    cch.LIVE_API_ALLOWED = False
    try:
        import bouzecode.backend.agent.providers.backends.anthropic_stream as _a
        import bouzecode.backend.agent.providers.backends.dispatch as _d
    except Exception:
        return
    _real = _a.stream_anthropic

    # `functools.wraps` is what makes this guard TRANSPARENT to introspection:
    # `*args, **kwargs` is correct here (a gate must never constrain the call),
    # but other wrappers installed on the same seam — e.g. the StreamCapture spy
    # in tests/methodology_cache_e2e_helpers.py — need to read the provider's
    # REAL signature to check they still mirror it. `wraps` sets `__wrapped__`,
    # so `inspect.signature`/`inspect.unwrap` see through the gate.
    @functools.wraps(_real)
    def _gated(*args, **kwargs):
        if not getattr(cch, "LIVE_API_ALLOWED", False):
            raise RuntimeError(
                "Real LLM call blocked: this test reached the live gateway without "
                "calling require_api_key(). Use MockLLM / e2e_harness for a "
                "deterministic fake, or call require_api_key() to opt in (it skips "
                "when credentials are absent)."
            )
        return _real(*args, **kwargs)

    monkeypatch.setattr(_a, "stream_anthropic", _gated, raising=False)
    monkeypatch.setattr(_d, "stream_anthropic", _gated, raising=False)


@pytest.fixture(autouse=True)
def _isolate_production_state(tmp_path, monkeypatch):
    """Aucun test ne doit écrire dans les données réelles de l'utilisateur.

    `src/bouzecode/web_v2/tests/` avait déjà cette garde, mais pas `tests/` — donc
    `tests/web_v2/` écrivait sans filet dans `~/.bouzecode/web_v2/tickets/tickets.db`.
    Constat : 1152 lignes de fixtures (slugs « proj » et « p ») dans le magasin de
    PRODUCTION, et une suite non déterministe puisque chaque run repartait d'un store
    différent. `TICKETS_DIR` doit être redirigé sur `_persistence` (la base SQLite est
    ouverte par `_persistence._db_path()`) ET sur `tickets`, son ré-export, encore lu
    par auto_resume / interrupted_report / migrations.
    """
    # Sorties d'outils tronquées (Bash, max_tool_output) : la sortie complète part dans un
    # fichier, par défaut ~/.bouzecode/tool_outputs. Un test qui ne choisit pas le dossier
    # écrivait donc dans le HOME réel. Un test qui le fixe lui-même (setenv) garde la main.
    monkeypatch.setenv("BOUZECODE_TOOL_OUTPUT_DIR", str(tmp_path / "tool_outputs"))
    # Le cache par jour des lectures d'activite Microsoft (ms_activite_cache) ecrit sous
    # ~/.bouzecode/cache/ms_activite : un test qui l'active remplirait le cache REEL de
    # l'utilisateur avec des mails inventes, ensuite servis a son assistant.
    monkeypatch.setenv(
        "BOUZECODE_MS_ACTIVITE_CACHE_DIR", str(tmp_path / "cache" / "ms_activite")
    )
    # Le CLI installe ripgrep dans ~/.local/bin s'il manque ; des tests lancent le vrai CLI
    # (en process ou en sous-process, avec le vrai HOME) : pas de téléchargement depuis un test.
    monkeypatch.setenv("BOUZECODE_RIPGREP_AUTO", "0")
    try:
        from bouzecode.web_v2.services.work import (
            _persistence, projects, tickets, worktrees,
        )
        from bouzecode.web_v2.tests.production_isolation import (
            isoler_l_identite_d_agent, isoler_le_parc_d_agents, isoler_les_fichiers_du_home,
        )
    except Exception:  # web_v2 absent d'un environnement réduit : rien à isoler
        yield
        return
    # Le parc d'agents RÉEL : sans ça, tout test atteignant `wake.tick()` balaie le warm-pool
    # des VRAIS agents et leur envoie `kill_agent`. Cf. production_isolation.py.
    isoler_le_parc_d_agents(tmp_path, monkeypatch)
    isoler_les_fichiers_du_home(tmp_path, monkeypatch)
    isoler_l_identite_d_agent(monkeypatch)
    tickets_dir = tmp_path / "tickets"
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tickets_dir)
    monkeypatch.setattr(tickets, "TICKETS_DIR", tickets_dir)
    # `_migrated` (slugs déjà importés du JSON legacy) est un set de PROCESS : le souvenir de
    # la base du test précédent est faux pour celui-ci, et il fait sauter en silence l'import
    # d'une graine legacy — un test qui croit avoir semé observe alors un store vide.
    monkeypatch.setattr(_persistence, "_migrated", set())
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "worktrees")
    monkeypatch.setattr(projects, "PROJECTS_PATH", tmp_path / "projects.json")
    yield


@pytest.fixture(autouse=True)
def _isolate_cli_logging(tmp_path, monkeypatch):
    """`cli.main()` route le logger `bouzecode` vers ~/.bouzecode/logs/cli-<pid>.log et coupe sa
    propagation. Un test qui appelle main() en process écrirait dans le journal RÉEL et
    rendrait `caplog` aveugle pour les tests suivants du même worker : on redirige le
    fichier et on restaure l'état du logger (handlers, niveau, propagation)."""
    import logging
    monkeypatch.setattr("bouzecode.backend.core.config.LOGS_DIR", tmp_path / "logs")
    logger = logging.getLogger("bouzecode")
    handlers, level, propagate = list(logger.handlers), logger.level, logger.propagate
    yield
    for handler in [h for h in logger.handlers if h not in handlers]:
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(level)
    logger.propagate = propagate


@pytest.fixture(autouse=True)
def _recalculs_de_l_arbre_termines():
    """Un recalcul de fond de l'arbre des agents (fleet_cache, thread daemon) lancé par un test
    ne doit pas déborder sur le suivant du même worker (il y appelait `list_agents`)."""
    yield
    from bouzecode.web_v2.services.work import fleet_cache
    fleet_cache.attendre_puis_vider()


@pytest.fixture(autouse=True)
def _isolate_global_state():
    """Snapshot and restore process-global registries around each test so a test
    that registers/disables tools or registers extra dirs cannot leak into the
    next one. This is what makes the suite order-independent (serial == xdist)."""
    # Working directory is process-global: a test that does os.chdir() (without
    # monkeypatch.chdir) would otherwise leak into every test that follows —
    # silently breaking project-root detection (RunPythonTest) and any code that
    # resolves relative paths. Restore it unconditionally so tests stay hermetic.
    _orig_cwd = os.getcwd()
    # Process environment is global too: a test that sets/pops os.environ directly
    # (without monkeypatch.setenv/delenv) leaks BOUZECODE_* flags and provider
    # credentials into the next test, making the suite order-dependent under xdist.
    _orig_env = dict(os.environ)
    snapshots = []  # (module, attr, restore_callable)

    def _snap_collection(modpath, attr):
        try:
            mod = __import__(modpath, fromlist=[attr.lstrip("_")])
        except Exception:
            return
        live = getattr(mod, attr, None)
        if isinstance(live, dict):
            saved = dict(live)
            snapshots.append(lambda: (live.clear(), live.update(saved)))
        elif isinstance(live, set):
            saved = set(live)
            snapshots.append(lambda: (live.clear(), live.update(saved)))
        elif isinstance(live, list):
            saved = list(live)
            snapshots.append(lambda: live.__setitem__(slice(None), saved))

    _snap_collection("bouzecode.backend.core.tool_registry", "_registry")
    _snap_collection("bouzecode.backend.core.tool_registry", "_disabled")
    _snap_collection("bouzecode.backend.core.paths", "_extra_dirs")
    yield
    os.chdir(_orig_cwd)  # restore cwd even if a test chdir'd away or deleted it
    if dict(os.environ) != _orig_env:  # restore env mutated without monkeypatch
        os.environ.clear()
        os.environ.update(_orig_env)
    for restore in snapshots:
        restore()


@pytest.fixture(autouse=True)
def _client_de_test_avec_jeton(monkeypatch):
    """Les mutations /api/ exigent le jeton local (web_v2/securite.py) : le client de test le
    joint comme le front, sans désactiver la garde (cf. web_v2/tests/client_jeton.py)."""
    from bouzecode.web_v2.tests.client_jeton import armer
    armer(monkeypatch)
