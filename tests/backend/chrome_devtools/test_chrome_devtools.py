"""Tests for the chrome-devtools launcher (mode B, transport-per-thread).

Uses a real (not mocked) stdio MCP server subprocess: fake_mcp_server.py.
Covers: eager flag on/off, lazy enable, idempotence, kill, and per-thread
transport isolation (parallelism).
"""
import json
import os
import sys
import threading
from pathlib import Path

import pytest

from bouzecode.backend.chrome_devtools import launcher
from bouzecode.backend.core import tool_registry

FAKE_SERVER = str(Path(__file__).parent / "fake_mcp_server.py")
NAV_TOOL = "mcp__chrome-devtools__navigate"
BOOTSTRAP = ("EnableChromeDevtools", "DisableChromeDevtools")


def _fake_args():
    return sys.executable, [FAKE_SERVER]


@pytest.fixture(autouse=True)
def _manifeste_isole(tmp_path, monkeypatch):
    """Le manifeste écrit par ces tests ne doit JAMAIS toucher `~/.bouzecode/`.

    Défaut réel, attrapé en vérifiant à la main : `enable_chrome_devtools(command=faux)`
    mémorise le `tools/list` du serveur, et le faux serveur de tests n'expose qu'un outil.
    Chaque exécution de la suite remplaçait donc le manifeste de l'INSTALLATION — 29 outils
    réels écrasés par 1 outil bidon — et le prochain agent ne se voyait plus qu'un
    `navigate` inventé. Un test qui écrit dans le HOME de l'utilisateur est un test qui
    casse sa machine ; l'isolation est ici, en autouse, pour qu'aucun test futur ne
    puisse l'oublier."""
    monkeypatch.setattr(launcher, "_manifest_path",
                        lambda: tmp_path / "chrome_devtools_manifest.json")
    yield


@pytest.fixture(autouse=True)
def _clean_launcher_state():
    """Ensure a pristine launcher + registry before and after each test."""
    launcher.shutdown_all()
    _purge_registry()
    os.environ.pop("BOUZECODE_ENABLE_CHROME_DEVTOOLS", None)
    yield
    launcher.shutdown_all()
    _purge_registry()
    os.environ.pop("BOUZECODE_ENABLE_CHROME_DEVTOOLS", None)


def _purge_registry():
    for name in (NAV_TOOL, *BOOTSTRAP):
        try:
            tool_registry.unregister_tool(name)
        except Exception:
            pass
        try:
            tool_registry.enable_tool(name)  # clear from disabled set
        except Exception:
            pass
        try:
            tool_registry.unregister_tool(name)
        except Exception:
            pass


# ── Eager path (import-time, flag-gated) ──────────────────────────────────────

def test_flag_on_declare_les_outils_SANS_demarrer_le_serveur(tmp_path, monkeypatch):
    """Le drapeau déclare la capacité navigateur ; il ne lance plus npx ni Chrome.

    Mesuré le 2026-07-30 : l'allumage au boot coûtait 4 à 6 s à CHAQUE agent (1,54 s sans,
    7,92 s avec) et c'était la première ligne du log, avant tout le reste — payée aussi par
    les agents `default` qui n'ouvrent jamais de navigateur. Les outils sont désormais
    déclarés depuis le manifeste mémorisé, et le serveur ne démarre qu'à la première
    utilisation réelle."""
    os.environ["BOUZECODE_ENABLE_CHROME_DEVTOOLS"] = "1"
    manifeste = tmp_path / "manifest.json"
    manifeste.write_text(json.dumps({"tools": [{"name": "navigate", "description": "d"}]}),
                         encoding="utf-8")
    monkeypatch.setattr(launcher, "_manifest_path", lambda: manifeste)

    count = launcher.register_chrome_devtools_tools()

    assert count == 1
    assert tool_registry.get_tool(NAV_TOOL) is not None
    assert NAV_TOOL not in tool_registry._disabled
    # LE POINT DU TEST : aucun serveur n'a été lancé pour en arriver là.
    assert not launcher._any_active(), "le boot ne doit plus démarrer de Chrome"


def test_sans_manifeste_le_boot_ne_declare_rien_et_ne_lance_rien(tmp_path, monkeypatch):
    """Première fois sur une machine : rien à déclarer, et surtout rien à démarrer.
    L'agent passe alors par `EnableChromeDevtools`, qui écrit le manifeste au passage —
    le cas ne se produit qu'une fois."""
    os.environ["BOUZECODE_ENABLE_CHROME_DEVTOOLS"] = "1"
    monkeypatch.setattr(launcher, "_manifest_path", lambda: tmp_path / "absent.json")

    assert launcher.register_chrome_devtools_tools() == 0
    assert not launcher._any_active()


def test_le_manifeste_est_memorise_au_premier_demarrage_reel(tmp_path, monkeypatch):
    """Le maillon qui rend le démarrage paresseux invisible : sans cette copie, ne pas
    lancer le serveur au boot reviendrait à ne pas déclarer les outils."""
    manifeste = tmp_path / "manifest.json"
    monkeypatch.setattr(launcher, "_manifest_path", lambda: manifeste)
    cmd, args = _fake_args()

    launcher.enable_chrome_devtools(command=cmd, args=args)

    assert manifeste.is_file(), "le tools/list du serveur doit être mémorisé"
    noms = [t["name"] for t in json.loads(manifeste.read_text(encoding="utf-8"))["tools"]]
    assert "navigate" in noms


def test_flag_off_registers_nothing():
    # env var absent
    cmd, args = _fake_args()
    count = launcher.register_chrome_devtools_tools(command=cmd, args=args)
    assert count == 0
    assert tool_registry.get_tool(NAV_TOOL) is None


# ── Lazy path (on-demand, flag-independent) ───────────────────────────────────

def test_lazy_enable_ignores_flag():
    # no env var, but enable_chrome_devtools must still work
    cmd, args = _fake_args()
    msg = launcher.enable_chrome_devtools(command=cmd, args=args)
    assert "activated" in msg
    tool = tool_registry.get_tool(NAV_TOOL)
    assert tool is not None
    result = tool.func({"url": "http://x"}, {})
    assert "navigated to http://x" in result


def test_enable_is_idempotent_per_thread():
    cmd, args = _fake_args()
    first = launcher.enable_chrome_devtools(command=cmd, args=args)
    assert "activated" in first
    second = launcher.enable_chrome_devtools(command=cmd, args=args)
    assert "already active" in second
    # only one transport for this thread
    assert len(launcher._TRANSPORTS) == 1


# ── Kill / teardown ───────────────────────────────────────────────────────────

def test_shutdown_removes_tools_and_kills_server():
    cmd, args = _fake_args()
    launcher.enable_chrome_devtools(command=cmd, args=args)
    assert tool_registry.get_tool(NAV_TOOL) is not None
    msg = launcher.shutdown_chrome_devtools()
    assert "stopped" in msg
    # last transport gone -> tools unregistered
    assert tool_registry.get_tool(NAV_TOOL) is None
    assert len(launcher._TRANSPORTS) == 0


def test_se_servir_d_un_outil_allume_chrome_tout_seul():
    """Utiliser l'outil SUFFIT : pas de tour perdu à appeler `EnableChromeDevtools` d'abord.

    C'est ce qui permet de ne plus rien démarrer au boot sans rien coûter à l'agent qui
    navigue vraiment. Le test appelle depuis un thread SANS transport — exactement la
    situation d'un agent au premier usage — et vérifie que l'appel aboutit."""
    cmd, args = _fake_args()
    launcher.enable_chrome_devtools(command=cmd, args=args)  # déclare les ToolDefs
    tool = tool_registry.get_tool(NAV_TOOL)

    # L'auto-allumage passe par npx en production ; ici on le renvoie sur le faux serveur.
    vrai_enable = launcher.enable_chrome_devtools
    launcher.enable_chrome_devtools = lambda **kw: vrai_enable(command=cmd, args=args)
    captured = {}

    def _call_from_other_thread():
        captured["result"] = tool.func({"url": "http://y"}, {})
        captured["actif"] = launcher.is_active()

    try:
        t = threading.Thread(target=_call_from_other_thread)
        t.start()
        t.join()
    finally:
        launcher.enable_chrome_devtools = vrai_enable

    assert captured["actif"], "l'appel doit avoir démarré un Chrome pour ce thread"
    assert "not active" not in captured["result"].lower()


def test_les_outils_survivent_a_un_arret_quand_la_capacite_est_declaree():
    """Après `DisableChromeDevtools`, les outils restent déclarés et se rallument au prochain
    usage. Les retirer rendrait le navigateur DÉFINITIVEMENT inaccessible : l'agent n'aurait
    plus aucun outil à appeler pour le relancer."""
    os.environ["BOUZECODE_ENABLE_CHROME_DEVTOOLS"] = "1"
    cmd, args = _fake_args()
    launcher.enable_chrome_devtools(command=cmd, args=args)
    assert tool_registry.get_tool(NAV_TOOL) is not None

    launcher.shutdown_chrome_devtools()

    assert not launcher.is_active(), "le Chrome de cet agent doit bien être fermé"
    assert tool_registry.get_tool(NAV_TOOL) is not None, \
        "les outils doivent rester appelables pour pouvoir rallumer"


# ── Per-thread isolation (parallelism, option 1) ──────────────────────────────

def test_parallel_isolation_one_chrome_per_thread():
    cmd, args = _fake_args()
    results = {}
    barrier = threading.Barrier(2)

    def _worker(tag):
        launcher.enable_chrome_devtools(command=cmd, args=args)
        barrier.wait()  # ensure both transports coexist
        tool = tool_registry.get_tool(NAV_TOOL)
        results[tag] = {
            "ident": threading.get_ident(),
            "nav": tool.func({"url": f"http://{tag}"}, {}),
        }

    ta = threading.Thread(target=_worker, args=("a",))
    tb = threading.Thread(target=_worker, args=("b",))
    ta.start(); tb.start()
    ta.join(); tb.join()

    # two distinct transports, keyed by thread ident
    assert results["a"]["ident"] != results["b"]["ident"]
    assert len(launcher._TRANSPORTS) == 2
    ta_trans = launcher._TRANSPORTS[results["a"]["ident"]]
    tb_trans = launcher._TRANSPORTS[results["b"]["ident"]]
    assert ta_trans is not tb_trans

    # each thread's call hit its OWN server subprocess (distinct PID)
    pid_a = results["a"]["nav"].split("pid=")[1].rstrip("]")
    pid_b = results["b"]["nav"].split("pid=")[1].rstrip("]")
    assert pid_a != pid_b
    assert "http://a" in results["a"]["nav"]
    assert "http://b" in results["b"]["nav"]


def test_shutdown_one_thread_leaves_others_alive():
    cmd, args = _fake_args()
    idents = {}
    ready = threading.Barrier(2)
    release_b = threading.Event()

    def _worker_a():
        launcher.enable_chrome_devtools(command=cmd, args=args)
        idents["a"] = threading.get_ident()
        ready.wait()
        # A shuts itself down
        launcher.shutdown_chrome_devtools()
        release_b.set()

    def _worker_b():
        launcher.enable_chrome_devtools(command=cmd, args=args)
        idents["b"] = threading.get_ident()
        ready.wait()
        release_b.wait(timeout=10)
        # B must still be alive after A's shutdown
        idents["b_alive_after"] = launcher._TRANSPORTS.get(threading.get_ident()) is not None

    ta = threading.Thread(target=_worker_a)
    tb = threading.Thread(target=_worker_b)
    ta.start(); tb.start()
    ta.join(); tb.join()

    assert idents["b_alive_after"] is True
    # A's transport gone, B's remains
    assert idents["a"] not in launcher._TRANSPORTS
    assert idents["b"] in launcher._TRANSPORTS
