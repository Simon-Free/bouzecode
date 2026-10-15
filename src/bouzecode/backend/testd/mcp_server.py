# [desc] testd : serveur MCP stdio (JSON-RPC 2.0 ligne par ligne, écrit à la main) qui expose RunPythonTest et TestStatus à Claude Code [/desc]
"""Claude Code reçoit la même mécanique de tests que les agents bouzecode : sélection impactée,
comparaison avec la base, file et budget de workers de la machine, navigateur chaud partagé,
délai par test, échecs regroupés. Lancement : `python -m bouzecode.backend.testd.mcp_server`.

Stdout est le canal du protocole : rien d'autre n'y passe. Au démarrage, le descripteur 1 est
dupliqué pour le protocole puis redirigé vers stderr (stdin, lui, vers devnull) (prints Python, écritures C, enfants qui
héritent du descripteur) ; le journal est `<dossier testd>/mcp.log`.

Dossier de l'agent : le cwd du process au lancement (celui du client MCP), ou l'argument
`cwd` d'un `tools/call` — un sous-agent Claude Code qui travaille dans un worktree y fait
`cd`, mais le serveur reste où il a été lancé. Une cible relative se lit depuis ce dossier :
dans un worktree, passer `cwd` (ou des cibles absolues)."""
from __future__ import annotations

import inspect
import json
import logging
import os
import sys
import threading
import traceback

VERSION_PROTOCOLE = "2025-06-18"
_VERSIONS_CONNUES = ("2024-11-05", "2025-03-26", "2025-06-18")
_OUTILS = ("RunPythonTest", "TestStatus")
_CWD = {"type": "string", "description": "Dossier de travail (worktree) ; défaut : celui du lancement du serveur."}

_journal = logging.getLogger("bouzecode.testd.mcp")


def retirer_python_home() -> None:
    """Le lanceur uv de bouzecode peut poser PYTHONHOME : il ne doit gagner ni le démon ni les
    pytest d'autres venvs (« SRE module mismatch », cf. shell_env.strip_inherited_python_home)."""
    from ..tools.ops.shell_env import strip_inherited_python_home
    garde = strip_inherited_python_home(dict(os.environ))
    for nom in [n for n in os.environ if n not in garde]:
        del os.environ[nom]


def outils_mcp() -> list[dict]:
    """Les schémas et descriptions de bouzecode tels quels, plus l'argument `cwd`."""
    from ..tools.schemas import TOOL_SCHEMAS
    outils = []
    for schema in TOOL_SCHEMAS:
        if schema["name"] in _OUTILS:
            entree = json.loads(json.dumps(schema["input_schema"]))
            entree["properties"]["cwd"] = _CWD
            outils.append({"name": schema["name"], "description": schema["description"],
                           "inputSchema": entree})
    return outils


def _run_python_test(arguments: dict) -> str:
    from ..tools.ops.test_runner import run_python_test
    acceptes = set(inspect.signature(run_python_test).parameters) - {"progression", "full"}
    #  Progression : la ligne du TUI n'a pas de place ici, et LigneProgression écrirait sur stderr.
    return run_python_test(progression=lambda _ligne: None,
                           **{k: v for k, v in arguments.items() if k in acceptes})


def _test_status(arguments: dict) -> str:
    from .rendu import statut_job
    return statut_job(arguments["job_id"], arguments.get("wait_s", 0), arguments.get("cancel", False))


def appeler_outil(nom: str, arguments: dict, dossier_lancement: str) -> tuple[str, bool]:
    """(texte, isError). Un run aux tests rouges n'est PAS une erreur : seul un refus
    (`Error: …`) ou une exception l'est, comme pour le harnais bouzecode."""
    from ..core.dossier_agent import Atelier, dans
    arguments = dict(arguments or {})
    dossier = os.path.join(dossier_lancement, arguments.pop("cwd", None) or "")
    if not os.path.isdir(dossier):
        return f"Error: cwd introuvable : {dossier}", True
    executer = {"RunPythonTest": _run_python_test, "TestStatus": _test_status}.get(nom)
    if executer is None:
        return f"Error: outil inconnu : {nom}", True
    with dans(Atelier(dossier=os.path.abspath(dossier))):
        texte = executer(arguments)
    return texte, texte.lstrip().startswith("Error:")


class Serveur:
    def __init__(self, protocole, dossier_lancement: str) -> None:
        self._protocole = protocole
        self._verrou = threading.Lock()
        self._dossier = dossier_lancement

    def envoyer(self, message: dict) -> None:
        with self._verrou:
            self._protocole.write(json.dumps(message, ensure_ascii=False) + "\n")
            self._protocole.flush()

    def _repondre(self, ident, resultat=None, erreur=None) -> None:
        corps = {"error": erreur} if erreur else {"result": resultat}
        self.envoyer({"jsonrpc": "2.0", "id": ident, **corps})

    def traiter(self, ligne: str) -> None:
        try:
            message = json.loads(ligne)
        except json.JSONDecodeError as exc:
            self._repondre(None, erreur={"code": -32700, "message": f"Parse error: {exc}"})
            return
        methode, ident = message.get("method"), message.get("id")
        params = message.get("params") or {}
        _journal.info("← %s id=%s", methode, ident)
        if ident is None:
            return  # notification (initialized, cancelled…) : pas de réponse
        if methode == "initialize":
            demandee = params.get("protocolVersion")
            self._repondre(ident, {
                "protocolVersion": demandee if demandee in _VERSIONS_CONNUES else VERSION_PROTOCOLE,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "bouzecode-tests", "version": _version()}})
        elif methode == "ping":
            self._repondre(ident, {})
        elif methode == "tools/list":
            self._repondre(ident, {"tools": outils_mcp()})
        elif methode == "tools/call":
            #  Un run dure des minutes : un fil par appel, le lecteur reste libre (ping, appels parallèles).
            threading.Thread(target=self._appel, args=(ident, params), daemon=True).start()
        else:
            self._repondre(ident, erreur={"code": -32601, "message": f"Method not found: {methode}"})

    def _appel(self, ident, params: dict) -> None:
        try:
            texte, en_erreur = appeler_outil(params.get("name"), params.get("arguments"), self._dossier)
        except Exception as exc:  # rendu au client comme résultat en erreur, et journalisé
            _journal.error("tools/call %s : %s", params.get("name"), traceback.format_exc())
            texte, en_erreur = f"Error: {type(exc).__name__}: {exc}", True
        _journal.info("→ %s id=%s isError=%s", params.get("name"), ident, en_erreur)
        self._repondre(ident, {"content": [{"type": "text", "text": texte}], "isError": en_erreur})


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("bouzecode")
    except PackageNotFoundError:
        return "0"


def _isoler_stdio():
    """(entrée, sortie) du protocole. Stdout (descripteur 1 compris) part désormais sur
    stderr, et stdin sur devnull : sous Windows, un enfant qui hérite du tube d'entrée pendant
    que le serveur y attend une ligne reste bloqué à son démarrage (`git rev-parse` de
    python_du_projet, mesuré : RunPythonTest ne rendait jamais la main)."""
    #  utf-8-sig : un tube PowerShell ouvre le flux par un BOM, qui casserait la 1re requête.
    entree = os.fdopen(os.dup(sys.stdin.fileno()), encoding="utf-8-sig")
    protocole = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", newline="\n")
    sys.stdout.flush()
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    nul = os.open(os.devnull, os.O_RDONLY)
    os.dup2(nul, sys.stdin.fileno())
    os.close(nul)
    sys.stdout = sys.stderr
    return entree, protocole


def _journaliser() -> None:
    from .common import dossier_testd
    gestionnaire = logging.FileHandler(dossier_testd() / "mcp.log", encoding="utf-8")
    gestionnaire.setFormatter(logging.Formatter("%(asctime)s %(process)d %(levelname)s %(message)s"))
    _journal.addHandler(gestionnaire)
    _journal.setLevel(logging.INFO)


def main() -> None:
    entree, protocole = _isoler_stdio()
    retirer_python_home()
    _journaliser()
    serveur = Serveur(protocole, os.getcwd())
    _journal.info("démarrage, cwd=%s", os.getcwd())
    for ligne in entree:
        if ligne.strip():
            serveur.traiter(ligne)
    _journal.info("stdin fermé : arrêt")


if __name__ == "__main__":
    main()
