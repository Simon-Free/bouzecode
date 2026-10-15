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
from bouzecode.paths import data_dir as bouzecode_data_dir

import atexit
import os
import re
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


def _image_en_fichier(item: dict) -> str:
    """Jamais de base64 en texte (rapport docs/reduction_tokens §4) : l'image va dans un
    fichier, le résultat n'en garde qu'une ligne ; ImageQuestion la regarde."""
    from ..tools.ops.image_ref import depuis_base64
    return depuis_base64(item.get("data", ""), item.get("mimeType", ""), "capture")


def _ressource(item: dict) -> str:
    ressource = item.get("resource") or {}
    return ressource.get("text") or f"[ressource {ressource.get('uri', '?')}]"


_TEXTE_PAR_TYPE = {
    "text": lambda item: item.get("text", ""),
    "image": _image_en_fichier,
    "resource": _ressource,
}


def _extract_text(result: dict) -> str:
    """Flatten an MCP tools/call result into a text string."""
    content = result.get("content") or []
    parts: List[str] = []
    for item in content:
        rendu = _TEXTE_PAR_TYPE.get(item.get("type")) if isinstance(item, dict) else None
        parts.append(rendu(item) if rendu else str(item))
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
            #  Avec les options que CET agent avait choisies (fenêtre visible, profil
            #  persistant) : un Chrome tombé, ou un nouveau process après une reprise, ne
            #  doit pas revenir en headless sur un profil jetable (TODO §5 du 2026-09-25).
            message = enable_chrome_devtools(**options_de_l_agent())
            tr = _TRANSPORTS.get(threading.get_ident())
            if tr is None or not tr.alive:
                return message  # actionnable : ce qui manque et comment l'installer
        try:
            arguments = _adapter_page_id(tool_name, dict(params or {}), tr)
            result = tr.request("tools/call", {"name": tool_name, "arguments": arguments})
        except Exception as e:  # noqa: BLE001
            return f"Error calling chrome-devtools tool '{tool_name}': {e}"
        texte = _extract_text(result)
        return texte + _alerte_page_de_login(texte)
    return _call


def is_active() -> bool:
    """True if the CALLER thread has a running chrome-devtools server."""
    tr = _TRANSPORTS.get(threading.get_ident())
    return tr is not None and tr.alive


def _any_active() -> bool:
    return any(tr.alive for tr in _TRANSPORTS.values())


# Ce que la description du serveur MCP ne dit pas : ce que le HARNAIS fait du résultat.
_COMPLEMENTS = {
    "take_screenshot": (
        " Harnais : l'image n'entre pas dans le résultat, elle est enregistrée dans un fichier "
        "dont le chemin est rendu ; pour l'examiner, ImageQuestion(paths=[chemin], question=...). "
        "Pour vérifier un contenu ou une structure (textes, éléments présents), préfère "
        "take_snapshot, qui rend du texte."
    ),
}


# ── pageId : exigé depuis chrome-devtools-mcp 1.8.0, refusé avant ──────────────
# Le harnais le complète : le modèle n'a pas à appeler `list_pages` avant chaque outil, et
# un manifeste mémorisé d'une autre version que le serveur lancé ne casse rien. Le schéma
# qui fait foi est celui du serveur EN COURS (son `tools/list`), pas celui annoncé au modèle.

# Schémas d'entrée du serveur en cours, par thread (nom court de l'outil → inputSchema).
_SCHEMAS_SERVEUR: Dict[int, Dict[str, dict]] = {}
_RE_PAGE_ID_SELECTIONNEE = re.compile(r"^\s*(\d+):.*\[selected\]\s*$", re.M)
_NOTE_PAGE_ID = (" Facultatif ici : sans lui, le harnais vise la page sélectionnée (selected) "
                 "de list_pages.")


def _schema_annonce(schema: Optional[dict]) -> dict:
    """Schéma montré au modèle : `pageId` y reste, mais n'est plus obligatoire."""
    if not schema:
        return {"type": "object", "properties": {}}
    proprietes = schema.get("properties") or {}
    if "pageId" not in proprietes:
        return schema
    annonce = dict(schema, properties=dict(proprietes))
    page_id = dict(proprietes["pageId"])
    page_id["description"] = (page_id.get("description") or "") + _NOTE_PAGE_ID
    annonce["properties"]["pageId"] = page_id
    annonce["required"] = [r for r in schema.get("required") or [] if r != "pageId"]
    return annonce


def _page_id_selectionnee(tr) -> Optional[int]:
    """Indice de la page sélectionnée, lu dans la sortie de `list_pages`."""
    try:
        texte = _extract_text(tr.request("tools/call", {"name": "list_pages", "arguments": {}}))
    except Exception:  # noqa: BLE001 — le serveur dira lui-même ce qui manque
        return None
    trouve = _RE_PAGE_ID_SELECTIONNEE.search(texte)
    return int(trouve.group(1)) if trouve else None


def _adapter_page_id(tool_name: str, arguments: dict, tr) -> dict:
    """Aligne `pageId` sur le contrat du serveur en cours.

    - serveur sans `pageId` (<= 1.7.0) : retiré (il refuse tout argument inconnu) ;
    - serveur qui l'attend : converti en nombre s'il est fourni (le protocole XML le passe
      en chaîne, refusée), sinon celui de la page sélectionnée est injecté."""
    schema = _SCHEMAS_SERVEUR.get(threading.get_ident(), {}).get(tool_name) or {}
    if "pageId" not in (schema.get("properties") or {}):
        arguments.pop("pageId", None)
        return arguments
    valeur = arguments.get("pageId")
    if isinstance(valeur, str) and valeur.strip().isdigit():
        arguments["pageId"] = int(valeur.strip())
    elif valeur is None or valeur == "":
        page_id = _page_id_selectionnee(tr)
        if page_id is None:
            arguments.pop("pageId", None)
        else:
            arguments["pageId"] = page_id
    return arguments


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
            "description": f"[MCP:{SERVER_NAME}] {tool.get('description', '')}"
                           + _COMPLEMENTS.get(tool_name, ""),
            "input_schema": _schema_annonce(tool.get("inputSchema")),
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


#  VERSION ÉPINGLÉE, testée de bout en bout le 2026-09-26 (headless : navigate_page puis
#  take_snapshot sur une page locale). Avec `@latest`, une nouvelle version changeait le contrat
#  des outils sous nos pieds : depuis 1.8.0, 28 outils sur 30 EXIGENT `pageId` (un nombre, celui
#  de `list_pages`), et tout `navigate_page` / `take_snapshot` sans lui échouait (« pageId:
#  Invalid input: expected number, received undefined »). Le code reste tolérant aux deux
#  contrats (cf. `_adapter_page_id`) ; monter de version = relancer le test réel
#  (BOUZECODE_CHROME_REEL=1, tests/backend/chrome_devtools/test_chrome_devtools_page_id.py).
#  Repli ponctuel : BOUZECODE_CHROME_DEVTOOLS_MCP_VERSION (ex. `latest`), validé.
#  NB : 1.10.0 ne démarre pas (sortie non JSON-RPC sur stdout) ; 1.10.1 est son correctif.
MCP_VERSION = "1.10.1"
MCP_PACKAGE = f"chrome-devtools-mcp@{MCP_VERSION}"
MCP_VERSION_ENV = "BOUZECODE_CHROME_DEVTOOLS_MCP_VERSION"


def mcp_package() -> str:
    """Spécification npm du serveur : version épinglée, ou celle de MCP_VERSION_ENV."""
    import re

    version = (os.environ.get(MCP_VERSION_ENV) or "").strip()
    if not version:
        return MCP_PACKAGE
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+-]*", version):
        raise ValueError(
            f"{MCP_VERSION_ENV}={version!r} n'est pas une version npm valide "
            f"(ex. {MCP_VERSION} ou latest).")
    return f"chrome-devtools-mcp@{version}"

# Args of the transport currently running for a given thread. Needed because the
# tool is idempotent per agent: to honour a LATER request for a visible window we
# must notice that the running Chrome was started with different args.
_TRANSPORT_ARGS: Dict[int, List[str]] = {}


def _racine_des_profils() -> "Path":
    """Dossier des profils persistants (point d'injection : les tests n'écrivent pas le HOME)."""
    from pathlib import Path
    return bouzecode_data_dir() / "chrome-profiles"


def profile_dir(name: str) -> "Path":
    """Directory hosting the PERSISTENT Chrome profile called `name`.

    Two different names always give two different directories: a named profile
    re-introduces exactly the risk `--isolated` avoids (parallel agents sharing a
    single user-data-dir lock each other out of navigation), so the name is the
    agent's responsibility — two agents must not ask for the same one at once.
    """
    from pathlib import Path

    safe = "".join(c if (c.isalnum() or c in "._-") else "-" for c in name).strip("-")
    target = _racine_des_profils() / (safe or "default")
    target.mkdir(parents=True, exist_ok=True)
    return target


def build_server_args(visible_window: bool = False,
                      profile: Optional[str] = None,
                      executable: Optional[str] = None) -> List[str]:
    """Command line for the chrome-devtools MCP server.

    Called with no argument it returns the historical default, byte for byte:
    `[MCP_PACKAGE, "--headless", "--isolated"]` (version épinglée, cf. MCP_VERSION).

    - `--headless`: Chrome renders offscreen (screenshots/snapshots/scripts all work),
      no window pops per agent. `visible_window=True` simply OMITS the flag (the
      server's own default is headless=false) so a HUMAN can act in the browser.
    - `--isolated`: fresh throwaway profile per agent so parallel agents don't
      share/lock the default profile (a cause of navigate timeouts). A `profile`
      name swaps it for `--userDataDir <dir>`, the option this server actually
      exposes for a persistent profile, so a session opened by hand SURVIVES a
      browser restart (pointless to type an OTP into a profile that dies).
    """
    args = [mcp_package()]
    if not visible_window:
        args.append("--headless")
    if profile:
        args += ["--userDataDir", str(profile_dir(profile))]
    else:
        args.append("--isolated")
    if executable:
        #  Chromium de secours (Playwright) : même réglage que Playwright, qui le lance sans
        #  bac à sable. Sur Ubuntu >= 24.04 (userns restreints par AppArmor), il plante sinon
        #  au démarrage (« Target closed ») — constaté le 2026-09-24.
        args += ["--executablePath", executable, "--chromeArg=--no-sandbox"]
    return args


# ── Navigateur : Chrome si présent, sinon un Chromium (Playwright) ─────────────
# chrome-devtools-mcp cherche Google Chrome « stable » par défaut. Une machine qui n'a que
# Firefox + le Chromium de Playwright échouait au démarrage, et l'agent concluait que la
# vérification navigateur était « impossible » (constaté le 2026-09-24 avec DeepSeek).

_NOMS_CHROME = ("google-chrome", "google-chrome-stable", "chrome")
_NOMS_CHROMIUM = ("chromium", "chromium-browser")
_CHEMINS_CHROME = (
    "/opt/google/chrome/chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)
_MOTIFS_PLAYWRIGHT = (
    "chromium-*/chrome-linux*/chrome",
    "chromium-*/chrome-win*/chrome.exe",
    "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
)


def _chrome_installe() -> bool:
    """Google Chrome est-il installé (ce que chrome-devtools-mcp sait trouver seul) ?"""
    import shutil
    if any(shutil.which(nom) for nom in _NOMS_CHROME):
        return True
    return any(os.path.isfile(chemin) for chemin in _CHEMINS_CHROME)


def dossiers_playwright() -> List["Path"]:
    """Où Playwright range ses navigateurs (variable d'environnement d'abord)."""
    from pathlib import Path
    dossiers = []
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        dossiers.append(Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]))
    dossiers.append(Path.home() / ".cache" / "ms-playwright")
    dossiers.append(Path.home() / "Library" / "Caches" / "ms-playwright")
    if os.environ.get("LOCALAPPDATA"):
        dossiers.append(Path(os.environ["LOCALAPPDATA"]) / "ms-playwright")
    return dossiers


def _chromium_de_secours() -> Optional[str]:
    """Un Chromium utilisable : celui du système, sinon le plus récent de Playwright."""
    import shutil
    for nom in _NOMS_CHROMIUM:
        chemin = shutil.which(nom)
        if chemin:
            return chemin
    for dossier in dossiers_playwright():
        candidats = sorted(str(c) for motif in _MOTIFS_PLAYWRIGHT for c in dossier.glob(motif))
        if candidats:
            return candidats[-1]
    return None


#  Points d'injection (tests) : pas de vrai navigateur ni de vrai `npx` dans la suite.
chrome_installe = _chrome_installe
chromium_de_secours = _chromium_de_secours


def _manque_pour_demarrer(command: str) -> Optional[str]:
    """Ce qui manque pour lancer le serveur, formulé comme une action ; None si rien."""
    import shutil
    if command == "npx" and not shutil.which("npx"):
        return ("Node.js/npx introuvable : chrome-devtools-mcp est un paquet npm. Installe Node "
                "(>= 22.12 LTS, https://nodejs.org), puis rappelle EnableChromeDevtools.")
    return None


def _navigateur_a_utiliser() -> tuple[Optional[str], Optional[str]]:
    """(chemin à passer en --executablePath ou None, message d'erreur actionnable ou None)."""
    if chrome_installe():
        return None, None
    chemin = chromium_de_secours()
    if chemin:
        return chemin, None
    return None, (
        "Aucun Chrome ni Chromium trouvé. Installe un Chromium DANS L'ENVIRONNEMENT DU PROJET "
        "(jamais globalement) : `.venv/bin/python -m pip install playwright && "
        ".venv/bin/python -m playwright install chromium`, puis rappelle EnableChromeDevtools. "
        "Le Chromium de Playwright est détecté automatiquement (PLAYWRIGHT_BROWSERS_PATH ou "
        "~/.cache/ms-playwright)."
    )


#  Dernière sortie d'erreur d'un démarrage raté, pour un message qui dit POURQUOI.
_DERNIERE_ERREUR: Dict[int, str] = {}


def _spawn_transport(command: str, args: Optional[List[str]]) -> Optional[StdioTransport]:
    """Spawn + handshake + tools/list a server for the CALLER thread.

    Returns the transport (and registers shared tools) or None on failure.
    Caller must hold `_lock`.
    """
    if args is None:
        args = build_server_args()
    #  npm_config_yes : npx installe le paquet s'il manque, sans question interactive (un agent
    #  n'a pas de terminal pour répondre « y » : le démarrage restait bloqué puis échouait).
    #  npm_config_prefer_offline : la version est figée (MCP_VERSION) et une version npm publiée
    #  est immuable ; si elle est en cache, npx la lance sans interroger le registre (~36 s
    #  mesurées sinon, au-delà du délai de 'initialize'). Absente du cache : téléchargée une fois.
    env = ({"npm_config_yes": "true", "npm_config_prefer_offline": "true"}
           if command == "npx" else {})
    transport = StdioTransport(ServerConfig(name=SERVER_NAME, command=command, args=args, env=env))
    try:
        transport.start()
        transport.request("initialize", INIT_PARAMS)
        transport.notify("notifications/initialized")
        listed = transport.request("tools/list")
    except Exception as e:  # noqa: BLE001
        stderr = getattr(transport, "stderr_output", "") or ""
        _DERNIERE_ERREUR[threading.get_ident()] = (f"{e}\n{stderr}").strip()
        print(f"[chrome-devtools] failed to start MCP server: {e}")
        transport.stop()
        return None

    _save_manifest(listed)
    _register_shared_tools(listed)
    _TRANSPORTS[threading.get_ident()] = transport
    _TRANSPORT_ARGS[threading.get_ident()] = list(args)
    _SCHEMAS_SERVEUR[threading.get_ident()] = {
        t.get("name"): t.get("inputSchema") or {} for t in listed.get("tools", [])}
    return transport


def _manifest_path():
    from pathlib import Path
    return bouzecode_data_dir() / "chrome_devtools_manifest.json"


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
    return declarer_depuis_le_manifeste()


def declarer_depuis_le_manifeste() -> int:
    """Déclare les outils depuis le manifeste mémorisé, sans démarrer de serveur (idempotent)."""
    with _lock:
        if _tools_registered:
            return len(_REGISTERED_NAMES)
        manifeste = _load_manifest()
        return _register_shared_tools(manifeste) if manifeste else 0


# Clé du JSON de session : les outils navigateur faisaient-ils partie de la liste envoyée ?
CLE_SESSION = "outils_navigateur"


def outils_declares() -> bool:
    """Les outils mcp__chrome-devtools__* sont-ils dans la liste envoyée au modèle ?"""
    return _tools_registered


def reprendre_les_outils_de_la_session(data: dict) -> int:
    """Une session REPRISE (réveil, message à un agent terminé) repart avec la même liste
    d'outils qu'à son dernier appel : les outils navigateur qu'elle avait sont redéclarés
    depuis le manifeste, Chrome ne se rallumant qu'à la première utilisation.

    Mesuré sur l'essai DeepSeek du 2026-09-24 (racine 6bafe9cd5ee7) : le nouveau process
    repartait sans eux, la liste d'outils rétrécissait de 29 854 caractères (≈ 8 000 tokens),
    tout ce qui la suit (note, historique) sortait du cache ; puis l'agent rappelait
    `EnableChromeDevtools` et la liste regrandissait — un second raté (tour 54 : 1 152 tokens
    lus en cache sur 42 704)."""
    options = (data or {}).get(CLE_OPTIONS) or {}
    if isinstance(options, dict) and (options.get("visible_window") or options.get("profile")):
        #  La fenêtre visible et le profil persistant choisis avant la reprise : le premier
        #  outil utilisé rallume Chrome AVEC eux (cf. `_make_tool_func`).
        _memoriser_options(bool(options.get("visible_window")), options.get("profile") or None)
    if not (data or {}).get(CLE_SESSION):
        return 0
    return declarer_depuis_le_manifeste()


# ── Options de l'agent : gardées tant qu'il ne les change pas ─────────────────
# Avant, les options n'existaient que dans les arguments du transport EN COURS. Transport
# mort (Chrome tombé) ou nouveau process (reprise de session, réveil web) : le premier
# outil rallumait Chrome avec le défaut `--headless --isolated`. L'humain perdait la
# fenêtre ET le profil persistant où il venait de saisir son OTP.
_OPTIONS: Dict[int, dict] = {}

# Clé du JSON de session : les options navigateur de l'agent, pour qu'une reprise les garde.
CLE_OPTIONS = "options_navigateur"


def options_de_l_agent() -> dict:
    """Options (`visible_window`, `profile`) demandées par l'agent APPELANT ; {} = défaut."""
    return dict(_OPTIONS.get(threading.get_ident()) or {})


def _memoriser_options(visible_window: bool, profile: Optional[str]) -> None:
    ident = threading.get_ident()
    if visible_window or profile:
        _OPTIONS[ident] = {"visible_window": bool(visible_window), "profile": profile or None}
    else:
        _OPTIONS.pop(ident, None)


# ── Escalade : page de login dans un Chrome headless ─────────────────────────
# Le démarrage paresseux ouvre Chrome en headless (le bon défaut : douze agents, zéro
# fenêtre). Mais quand la page atteinte demande une action HUMAINE (SSO, OTP, captcha),
# rien ne le disait : l'agent priait l'utilisateur de « se connecter dans la fenêtre »
# d'un navigateur qui n'en a pas, ou concluait à un blocage. Le résultat de l'outil porte
# désormais la marche à suivre, une fois par site.

_ALERTES_LOGIN: Dict[int, set] = {}

#  Page sélectionnée dans la liste des pages et URL de la racine d'un snapshot
#  (« RootWebArea "…" url="https://…" ») : l'URL où l'on a ATTERRI, redirections comprises.
#  Jamais les URL des liens de la page : un lien « Se connecter » sur une page ordinaire n'est
#  pas une page de login. La liste des pages a deux formes : « 1: https://… [selected] » (page
#  sans titre) et, relevé sur chrome-devtools-mcp le 2026-09-26, « 1: <titre> (https://…)
#  [selected] » — la seule que rend une vraie page de SSO (elle a un titre). L'URL est donc la
#  DERNIÈRE avant « [selected] », parenthèse fermante exclue.
_RE_PAGE_SELECTIONNEE = re.compile(r"^\s*\d+:.*?(https?://\S+?)\)?\s+\[selected\]", re.M)
_RE_RACINE_SNAPSHOT = re.compile(r'RootWebArea\b[^\n]*?\burl="([^"]+)"')
_PREFIXES_HOTE_LOGIN = ("login.", "logon.", "signin.", "sso.", "auth.", "idp.", "adfs.",
                        "accounts.")
_FOURNISSEURS_IDENTITE = ("microsoftonline.com", "login.live.com", "okta.com", "auth0.com",
                          "onelogin.com", "pingidentity.com", "pingone.", "duosecurity.com")
_RE_CHEMIN_LOGIN = re.compile(
    r"/(login|logon|signin|sign-in|sign_in|sso|saml2?|adfs|mfa|2fa|otp|cas/login"
    r"|oauth2?(/v2\.0)?/authorize|protocol/openid-connect/auth)(?=/|\.[a-z]+$|$)", re.I)
_RE_CHAMP_SECRET = re.compile(
    r'textbox "[^"\n]*(password|mot de passe|passcode|one-time|\botp\b|verification code'
    r'|code de v[ée]rification|security code|code de s[ée]curit[ée]|usage unique)[^"\n]*"',
    re.I)
_RE_CAPTCHA = re.compile(
    r"\b(re|h)?captcha\b|turnstile|i'?m not a robot|je ne suis pas un robot"
    r"|verify you are human|v[ée]rifiez que vous [êe]tes (un )?humain", re.I)
_HOTES_LOCAUX = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


def _url_de_la_page(texte: str) -> Optional[str]:
    for motif in (_RE_PAGE_SELECTIONNEE, _RE_RACINE_SNAPSHOT):
        trouve = motif.search(texte)
        if trouve:
            return trouve.group(1)
    return None


def _hote_local(hote: str) -> bool:
    return hote in _HOTES_LOCAUX or hote.startswith("127.") or hote.endswith(".localhost")


def page_de_connexion(texte: str) -> Optional[tuple[str, str]]:
    """(site, motif) si la page décrite par `texte` attend un humain (SSO/OTP/captcha), sinon None.

    L'application LOCALE que l'agent teste lui-même n'est jamais signalée : il en a les
    identifiants de test, aucun humain n'est requis."""
    from urllib.parse import urlsplit

    url = _url_de_la_page(texte)
    hote = ""
    if url:
        morceaux = urlsplit(url)
        hote = (morceaux.hostname or "").lower()
        if _hote_local(hote):
            return None
        if (hote.startswith(_PREFIXES_HOTE_LOGIN)
                or any(f in hote for f in _FOURNISSEURS_IDENTITE)
                or _RE_CHEMIN_LOGIN.search(morceaux.path or "")):
            return hote, "page d'authentification"
    if _RE_CHAMP_SECRET.search(texte):
        return hote or "?", "champ mot de passe / code à usage unique"
    if _RE_CAPTCHA.search(texte):
        return hote or "?", "captcha"
    return None


def profil_suggere(site: str) -> str:
    """Nom de profil persistant proposé pour un site : la session ouverte y reste."""
    propre = "".join(c if (c.isalnum() or c in "._-") else "-" for c in site).strip("-.")
    return f"sso-{propre}" if propre else "sso"


def _alerte_page_de_login(texte: str) -> str:
    """Note ajoutée au résultat quand un Chrome HEADLESS atterrit sur une page de login."""
    ident = threading.get_ident()
    if "--headless" not in _TRANSPORT_ARGS.get(ident, ()):
        return ""  # fenêtre déjà visible (ou serveur de test) : l'humain peut agir
    detection = page_de_connexion(texte)
    if detection is None:
        return ""
    site, motif = detection
    deja = _ALERTES_LOGIN.setdefault(ident, set())
    if site in deja:
        return ""
    deja.add(site)
    return (
        f"\n\n[harnais] {motif.capitalize()} détecté(e) sur {site} alors que ce Chrome est "
        "HEADLESS : il n'a AUCUNE fenêtre, l'utilisateur ne peut rien y saisir (SSO, OTP, "
        "captcha). Si une action humaine est nécessaire, appelle "
        f'EnableChromeDevtools(visible_window=true, profile="{profil_suggere(site)}") : Chrome '
        "est relancé avec une vraie fenêtre et un profil persistant (la session ouverte survit "
        "aux redémarrages et aux reprises ; les options sont gardées). Renavigue ensuite vers "
        "l'URL voulue, puis demande à l'utilisateur (AskUserQuestion) de s'authentifier dans "
        "la fenêtre et de te prévenir. Si tu as toi-même les identifiants, ignore cette note."
    )


def enable_chrome_devtools(command: str = "npx", args: Optional[List[str]] = None,
                           visible_window: bool = False,
                           profile: Optional[str] = None) -> str:
    """LAZY path: start chrome-devtools for the CALLER agent, ignoring the flag.

    Idempotent per thread AS LONG AS the requested command line is unchanged: a
    given agent reuses its own Chrome, different agents (threads) each get their
    own. But an agent that already lit Chrome HEADLESS and then discovers a login
    page needs a real window: when the requested args differ from the running
    ones we STOP the transport and start a new one, otherwise the human would be
    asked to type an OTP into a browser that has no window.

    `command`/`args` injectable for tests; `args` (when given) wins over
    `visible_window`/`profile`.
    """
    with _lock:
        if args is None:
            _memoriser_options(visible_window, profile)
            manque = _manque_pour_demarrer(command)
            executable, pas_de_navigateur = _navigateur_a_utiliser()
            if manque or pas_de_navigateur:
                return manque or pas_de_navigateur
            wanted = build_server_args(visible_window, profile, executable)
        else:
            wanted = list(args)
        ident = threading.get_ident()
        if is_active():
            if _TRANSPORT_ARGS.get(ident) == wanted:
                return (
                    f"chrome-devtools already active for this agent "
                    f"({len(_REGISTERED_NAMES)} tool(s) available). Use the "
                    f"mcp__chrome-devtools__* tools to drive your Chrome."
                )
            _teardown_ident(ident)
        tr = _spawn_transport(command, wanted)
        if tr is None:
            return _message_d_echec(wanted)
        return (
            f"chrome-devtools activated for this agent: {len(_REGISTERED_NAMES)} "
            f"tool(s) available as mcp__chrome-devtools__*. They appear next turn."
        )


def _message_d_echec(args: List[str]) -> str:
    """Pourquoi le serveur n'a pas démarré, avec la sortie d'erreur et quoi faire."""
    detail = _DERNIERE_ERREUR.pop(threading.get_ident(), "").strip()
    lignes = [f"Échec du démarrage de chrome-devtools-mcp (`npx {' '.join(args)}`)."]
    if detail:
        lignes.append("Sortie d'erreur :\n" + "\n".join(detail.splitlines()[-8:]))
    if "does not support Node" in detail:
        lignes.append("→ Node trop ancien : installe Node >= 22.12 LTS (https://nodejs.org).")
    else:
        lignes.append("→ Vérifie Node >= 22.12 et le navigateur ; sans Chrome, installe un "
                      "Chromium dans le projet : `.venv/bin/python -m pip install playwright && "
                      ".venv/bin/python -m playwright install chromium`.")
    return "\n".join(lignes)


def _teardown_ident(ident: int) -> bool:
    """Kill and drop the transport for a specific thread. Caller holds `_lock`."""
    _TRANSPORT_ARGS.pop(ident, None)
    _SCHEMAS_SERVEUR.pop(ident, None)
    _ALERTES_LOGIN.pop(ident, None)
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
        # Demande explicite de fermeture : le prochain Chrome repart du défaut (headless).
        _OPTIONS.pop(ident, None)
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
        _OPTIONS.clear()
        removed = _unregister_shared_tools()
        return f"chrome-devtools: killed {killed} server(s), unregistered {removed} tool(s)."


# ── Bootstrap tools (always-on): let an agent turn Chrome on/off at runtime ────

def _enable_tool_func(params: dict, config: dict) -> str:
    # `profile or None`: an empty string from the model must fall back to the
    # throwaway --isolated profile, not create a persistent one called "default".
    return enable_chrome_devtools(
        visible_window=bool(params.get("visible_window")),
        profile=params.get("profile") or None,
    )


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
                "is not already active for you. Idempotent per agent, EXCEPT when "
                "you ask for different options (visible_window/profile): the "
                "running Chrome is then stopped and relaunched with them, so you "
                "can switch to a visible window after discovering a login page. "
                "Browser tools also start Chrome by themselves (headless by default); "
                "when one of them lands on a login page (SSO, OTP, captcha) in a "
                "headless Chrome, its result tells you so and gives the exact call "
                "to make. The options you pass are remembered for THIS agent until "
                "DisableChromeDevtools: they are kept when Chrome restarts and when "
                "the session is resumed, so the window and the logged-in profile "
                "survive."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "visible_window": {
                        "type": "boolean",
                        "description": (
                            "Launch Chrome WITH a real window on the user's screen "
                            "instead of headless. Use ONLY when a HUMAN must act in "
                            "the browser: multi-factor/OTP authentication, SSO login, "
                            "captcha, a consent dialog. NOT for debugging comfort — "
                            "a dozen agents run in parallel and each window pops on "
                            "the user's desktop. Default false (headless, offscreen: "
                            "screenshots, snapshots and scripts all work)."
                        ),
                    },
                    "profile": {
                        "type": "string",
                        "description": (
                            "Name of a PERSISTENT Chrome profile (stored under "
                            "~/.bouzecode/chrome-profiles/<name>) instead of the "
                            "default throwaway one. Use it together with "
                            "visible_window so the session the human just opened "
                            "SURVIVES a browser restart — otherwise you make the "
                            "user type an OTP only to lose it. Pick a name specific "
                            "to your task (e.g. 'confluence-otp-<ticket>'): two "
                            "agents must NOT use the same profile at the same time, "
                            "they would lock each other's user-data-dir."
                        ),
                    },
                },
            },
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
