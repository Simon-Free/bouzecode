# [desc] Launches chrome-devtools MCP servers (one Chrome per agent thread) and registers their browser tools. [/desc]
"""Launch chrome-devtools MCP servers and register their tools.

Concurrency model: sub-agents run as threads of a ThreadPoolExecutor
(SubAgentManager.spawn). Each thread gets its OWN chrome-devtools server
subprocess (its own Chrome), indexed by `threading.get_ident()`. This gives
real parallel visual debugging: N sub-agents = N threads = N transports = N
Chrome instances, isolated from each other.

The tool registry is global (one name = one ToolDef), so the qualified tools
`mcp__chrome-devtools__<tool>` are registered ONCE (on the first enable, from
any thread). Their `func` resolves the CALLER's transport at execution time via
`threading.get_ident()`, dispatching each call to that agent's own Chrome.

Two activation paths:
  1. EAGER — `register_chrome_devtools_tools()` at import time from
     tools/registration.py; only acts when `BOUZECODE_ENABLE_CHROME_DEVTOOLS == "1"`.
  2. LAZY — the always-on `EnableChromeDevtools` tool calls
     `enable_chrome_devtools()` on demand (ignores the flag).

Lifecycle: `DisableChromeDevtools` calls `shutdown_chrome_devtools()` which
kills the CALLER's server subprocess; `shutdown_all()` (atexit) kills every
remaining server. When the last transport is gone the shared ToolDefs are
unregistered.
"""
from __future__ import annotations

import atexit
import os
import threading
from typing import Dict, List, Optional

from ..core.tool_registry import (
    ToolDef,
    register_tool,
    unregister_tool,
    enable_tool,
    disable_tool,
)
from .transport import ServerConfig, StdioTransport

SERVER_NAME = "chrome-devtools"
PROTOCOL_VERSION = "2024-11-05"
INIT_PARAMS = {
    "protocolVersion": PROTOCOL_VERSION,
    "capabilities": {"tools": {}, "roots": {"listChanged": False}},
    "clientInfo": {"name": "bouzecode", "version": "1.0.0"},
}

# One transport (= one Chrome) per caller thread. Sub-agents are pool threads,
# so each has its own entry keyed by threading.get_ident().
_TRANSPORTS: Dict[int, StdioTransport] = {}
# The mcp__chrome-devtools__* ToolDefs are shared and registered once.
_REGISTERED_NAMES: List[str] = []
_tools_registered = False
_lock = threading.RLock()


def _extract_text(result: dict) -> str:
    """Flatten an MCP tools/call result into a text string."""
    content = result.get("content") or []
    parts: List[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
        else:
            parts.append(str(item))
    text = "\n".join(parts) if parts else ""
    if result.get("isError"):
        return f"[chrome-devtools error] {text}"
    return text


def _make_tool_func(tool_name: str):
    """Build a tool func that resolves the CALLER's transport at call time.

    Not bound to a fixed transport: each thread (agent) dispatches to its own
    Chrome via threading.get_ident().
    """
    def _call(params: dict, config: dict) -> str:
        tr = _TRANSPORTS.get(threading.get_ident())
        if tr is None or not tr.alive:
            # DÉMARRAGE À LA PREMIÈRE UTILISATION. Se servir de l'outil suffit à allumer
            # Chrome : pas de tour perdu à appeler `EnableChromeDevtools` d'abord, et
            # surtout aucun agent ne paie un Chrome qu'il n'ouvrira jamais. C'est ce qui
            # permet de ne PLUS rien démarrer au boot (cf. register_chrome_devtools_tools) :
            # mesuré, l'allumage eager coûtait 4 à 6 s à CHAQUE agent — npx résolvant
            # `chrome-devtools-mcp@latest` puis un Chrome — première ligne du log, avant
            # tout le reste, pour un agent `default` qui ne navigue jamais.
            enable_chrome_devtools()
            tr = _TRANSPORTS.get(threading.get_ident())
            if tr is None or not tr.alive:
                return (
                    "chrome-devtools could not be started for this agent (is `npx` "
                    "available? is Node installed?). See logs."
                )
        try:
            result = tr.request("tools/call", {"name": tool_name, "arguments": params or {}})
        except Exception as e:  # noqa: BLE001
            return f"Error calling chrome-devtools tool '{tool_name}': {e}"
        return _extract_text(result)
    return _call


def is_active() -> bool:
    """True if the CALLER thread has a running chrome-devtools server."""
    tr = _TRANSPORTS.get(threading.get_ident())
    return tr is not None and tr.alive


def _any_active() -> bool:
    return any(tr.alive for tr in _TRANSPORTS.values())


def _register_shared_tools(listed: dict) -> int:
    """Register the shared mcp__chrome-devtools__* ToolDefs once (any thread)."""
    global _tools_registered
    if _tools_registered:
        return len(_REGISTERED_NAMES)
    count = 0
    for tool in listed.get("tools", []):
        tool_name = tool.get("name")
        if not tool_name:
            continue
        qualified = f"mcp__{SERVER_NAME}__{tool_name}"
        annotations = tool.get("annotations") or {}
        schema = {
            "name": qualified,
            "description": f"[MCP:{SERVER_NAME}] {tool.get('description', '')}",
            "input_schema": tool.get("inputSchema") or {"type": "object", "properties": {}},
        }
        register_tool(ToolDef(
            name=qualified,
            schema=schema,
            func=_make_tool_func(tool_name),
            read_only=bool(annotations.get("readOnlyHint", False)),
            concurrent_safe=False,
        ))
        enable_tool(qualified)
        _REGISTERED_NAMES.append(qualified)
        count += 1
    _tools_registered = True
    if count:
        print(f"[chrome-devtools] registered {count} shared tool(s)")
    return count


def _unregister_shared_tools() -> int:
    global _tools_registered
    removed = 0
    for name in list(_REGISTERED_NAMES):
        try:
            disable_tool(name)
        except Exception:  # noqa: BLE001
            pass
        try:
            unregister_tool(name)
        except Exception:  # noqa: BLE001
            pass
        removed += 1
    _REGISTERED_NAMES.clear()
    _tools_registered = False
    return removed


def _spawn_transport(command: str, args: Optional[List[str]]) -> Optional[StdioTransport]:
    """Spawn + handshake + tools/list a server for the CALLER thread.

    Returns the transport (and registers shared tools) or None on failure.
    Caller must hold `_lock`.
    """
    if args is None:
        # --headless: Chrome renders offscreen (screenshots/snapshots/scripts all work),
        # no window pops per agent. --isolated: fresh throwaway profile per agent so
        # parallel agents don't share/lock the default profile (a cause of navigate timeouts).
        args = ["chrome-devtools-mcp@latest", "--headless", "--isolated"]
    transport = StdioTransport(ServerConfig(name=SERVER_NAME, command=command, args=args))
    try:
        transport.start()
        transport.request("initialize", INIT_PARAMS)
        transport.notify("notifications/initialized")
        listed = transport.request("tools/list")
    except Exception as e:  # noqa: BLE001
        print(f"[chrome-devtools] failed to start MCP server: {e}")
        transport.stop()
        return None

    _save_manifest(listed)
    _register_shared_tools(listed)
    _TRANSPORTS[threading.get_ident()] = transport
    return transport


def _manifest_path():
    from pathlib import Path
    return Path.home() / ".bouzecode" / "chrome_devtools_manifest.json"


def _save_manifest(listed: dict) -> None:
    """Mémorise le `tools/list` du serveur pour pouvoir déclarer les outils SANS le lancer.

    C'est la pièce qui rend le démarrage paresseux invisible : les noms et schémas des 29
    outils ne sont connus que du serveur MCP. Sans cette copie, ne pas le démarrer au boot
    reviendrait à ne pas déclarer les outils, et le modèle ne pourrait pas « juste s'en
    servir » — il faudrait un tour pour appeler `EnableChromeDevtools`."""
    import json
    chemin = _manifest_path()
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(listed), encoding="utf-8")
    except OSError:
        pass  # un manifeste non écrit ne coûte qu'un tour au prochain démarrage


def _load_manifest() -> Optional[dict]:
    import json
    chemin = _manifest_path()
    if not chemin.is_file():
        return None
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def register_chrome_devtools_tools(command: str = "npx", args: Optional[List[str]] = None) -> int:
    """EAGER path: called at import time. No-op unless the flag is set.

    NE DÉMARRE PLUS RIEN. Il déclare les outils depuis le manifeste mémorisé ; le serveur
    MCP (npx + Chrome) n'est lancé qu'à la PREMIÈRE utilisation réelle d'un de ces outils
    (cf. `_make_tool_func`).

    Mesuré le 2026-07-30 : l'allumage au boot coûtait 4 à 6 s à CHAQUE agent — `boot sans`
    1,54 s contre `boot avec` 7,92 s — et c'était la PREMIÈRE ligne du log, avant tout le
    reste. `bouzeui.ps1` posant le drapeau, l'env était hérité par tous les agents : un
    `default` qui n'ouvrira jamais un navigateur payait npx (résolution de
    `chrome-devtools-mcp@latest`) puis un Chrome, et les gardait résidents. Douze
    sous-agents = douze Chrome ; 123 process python/node/chrome relevés sur la machine.

    Sans manifeste (première fois sur une machine), rien n'est déclaré et l'agent passe par
    `EnableChromeDevtools`, qui écrit le manifeste au passage. Le cas ne se produit qu'une
    fois.
    """
    if os.environ.get("BOUZECODE_ENABLE_CHROME_DEVTOOLS") != "1":
        return 0
    with _lock:
        if _tools_registered:
            return len(_REGISTERED_NAMES)
        manifeste = _load_manifest()
        return _register_shared_tools(manifeste) if manifeste else 0


def enable_chrome_devtools(command: str = "npx", args: Optional[List[str]] = None) -> str:
    """LAZY path: start chrome-devtools for the CALLER agent, ignoring the flag.

    Idempotent per thread: a given agent reuses its own Chrome. Different agents
    (threads) each get their own. `command`/`args` injectable for tests.
    """
    with _lock:
        if is_active():
            return (
                f"chrome-devtools already active for this agent "
                f"({len(_REGISTERED_NAMES)} tool(s) available). Use the "
                f"mcp__chrome-devtools__* tools to drive your Chrome."
            )
        tr = _spawn_transport(command, args)
        if tr is None:
            return (
                "Failed to start chrome-devtools MCP server (is `npx` and "
                "`chrome-devtools-mcp` available? is Node installed?). See logs."
            )
        return (
            f"chrome-devtools activated for this agent: {len(_REGISTERED_NAMES)} "
            f"tool(s) available as mcp__chrome-devtools__*. They appear next turn."
        )


def _teardown_ident(ident: int) -> bool:
    """Kill and drop the transport for a specific thread. Caller holds `_lock`."""
    tr = _TRANSPORTS.pop(ident, None)
    if tr is None:
        return False
    try:
        tr.stop()
    except Exception:  # noqa: BLE001
        pass
    return True


def shutdown_chrome_devtools() -> str:
    """Kill the CALLER agent's chrome-devtools server subprocess.

    Les OUTILS restent déclarés quand la capacité navigateur est activée pour ce process
    (`BOUZECODE_ENABLE_CHROME_DEVTOOLS=1`) : ils sont désormais déclarés depuis le manifeste,
    sans serveur, et se rallument à la première utilisation. Les retirer ici rendrait le
    navigateur définitivement inaccessible après un `DisableChromeDevtools` — l'agent
    n'aurait plus aucun outil à appeler pour le relancer. On ne les retire donc que lorsque
    la capacité n'est PAS déclarée : dans ce cas ils n'existaient que le temps du serveur.
    """
    with _lock:
        ident = threading.get_ident()
        if not _teardown_ident(ident):
            return "chrome-devtools was not running for this agent."
        msg = "chrome-devtools stopped for this agent; Chrome closed."
        capacite_declaree = os.environ.get("BOUZECODE_ENABLE_CHROME_DEVTOOLS") == "1"
        if not _any_active() and not capacite_declaree:
            removed = _unregister_shared_tools()
            msg += f" No agent left using it — {removed} tool(s) unregistered."
        return msg


def shutdown_all() -> str:
    """Kill EVERY chrome-devtools server (all agents) and unregister the tools.

    Used as the atexit safety net against orphaned Chrome/npx subprocesses.
    """
    with _lock:
        killed = 0
        for ident in list(_TRANSPORTS.keys()):
            if _teardown_ident(ident):
                killed += 1
        removed = _unregister_shared_tools()
        return f"chrome-devtools: killed {killed} server(s), unregistered {removed} tool(s)."


# ── Bootstrap tools (always-on): let an agent turn Chrome on/off at runtime ────

def _enable_tool_func(params: dict, config: dict) -> str:
    return enable_chrome_devtools()


def _disable_tool_func(params: dict, config: dict) -> str:
    return shutdown_chrome_devtools()


BOOTSTRAP_TOOL_NAMES = ("EnableChromeDevtools", "DisableChromeDevtools")


def register_bootstrap_tools() -> None:
    """Register the always-on Enable/DisableChromeDevtools tools + enable them.

    Called from tools/registration.py AFTER the whitelist pass so the
    enable_tool() calls survive the global disable.
    """
    register_tool(ToolDef(
        name="EnableChromeDevtools",
        schema={
            "name": "EnableChromeDevtools",
            "description": (
                "Start a chrome-devtools MCP server on demand for THIS agent and "
                "expose its browser-automation tools (navigate, screenshot, "
                "DOM/CSS inspection) as mcp__chrome-devtools__*. Each agent gets "
                "its own Chrome instance. Call this before driving Chrome when it "
                "is not already active for you. Idempotent per agent."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        func=_enable_tool_func,
        read_only=False,
        concurrent_safe=False,
    ))
    enable_tool("EnableChromeDevtools")

    register_tool(ToolDef(
        name="DisableChromeDevtools",
        schema={
            "name": "DisableChromeDevtools",
            "description": (
                "Stop THIS agent's chrome-devtools MCP server and close its Chrome "
                "instance (frees resources). Call this when your browser debugging "
                "is finished. Other agents' Chrome instances are unaffected."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        func=_disable_tool_func,
        read_only=False,
        concurrent_safe=False,
    ))
    enable_tool("DisableChromeDevtools")


# Safety net: kill any orphaned Chrome/npx subprocess when the process exits.
atexit.register(shutdown_all)
