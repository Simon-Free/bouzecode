# [desc] testd, du point de vue de Claude Code : le VRAI serveur MCP stdio, piloté en JSON-RPC, lance RunPythonTest (démon privé ou chemin direct) sur un projet jetable ; stdout ne porte que du JSON [/desc]
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import bouzecode
from tests.backend.testd.aides import projet

_SRC = str(Path(bouzecode.__file__).resolve().parents[1])
#  PYTHONHOME valide (le serveur doit démarrer) mais reconnaissable : séparateur final.
_PYTHON_HOME_DU_LANCEUR = sys.base_prefix.rstrip("\\/") + os.sep
_UN_VERT_UN_ROUGE = {
    "test_mixte.py": """
        import os

        def test_vert():
            assert True

        def test_rouge():
            assert 1 == 2, "attendu rouge"

        def test_sans_le_python_home_du_serveur():
            # le lanceur du venv pose le sien (sans séparateur final) : seul celui du serveur en a un
            assert not os.environ.get("PYTHONHOME", "").endswith(os.sep), os.environ["PYTHONHOME"]
    """,
}


class ClientMcp:
    """Le serveur réel en sous-process ; chaque ligne de stdout est gardée telle quelle."""

    def __init__(self, cwd: Path, journal: Path, **variables: str) -> None:
        env = {**os.environ, "PYTHONPATH": _SRC, **variables}
        self.lignes: list[str] = []
        self._recues: queue.Queue = queue.Queue()
        self._journal = open(journal, "w", encoding="utf-8")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "bouzecode.backend.testd.mcp_server"], cwd=str(cwd), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._journal,
            encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self._lire, daemon=True).start()
        self._suivant = 0

    def _lire(self) -> None:
        for ligne in self.process.stdout:
            self.lignes.append(ligne)
            self._recues.put(ligne)

    def demander(self, methode: str, params: dict | None = None, delai_s: float = 240) -> dict:
        self._suivant += 1
        self.notifier(methode, params, ident=self._suivant)
        reponse = json.loads(self._recues.get(timeout=delai_s))
        assert reponse["id"] == self._suivant, reponse
        return reponse

    def notifier(self, methode: str, params: dict | None = None, ident=None) -> None:
        message = {"jsonrpc": "2.0", "method": methode, **({"params": params} if params else {})}
        if ident is not None:
            message["id"] = ident
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def fermer(self) -> None:
        self.process.stdin.close()
        self.process.wait(timeout=30)
        self._journal.close()


def _dialogue_complet(tmp_path: Path, **variables: str) -> tuple[ClientMcp, dict, dict, dict]:
    projet(tmp_path / "jetable", _UN_VERT_UN_ROUGE)
    client = ClientMcp(tmp_path, tmp_path / "stderr.txt", BZ_TESTD_HOME=str(tmp_path / "testd_home"),
                       PYTHONHOME=_PYTHON_HOME_DU_LANCEUR, **variables)
    init = client.demander("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                          "clientInfo": {"name": "test", "version": "0"}})
    client.notifier("notifications/initialized")
    liste = client.demander("tools/list")
    appel = client.demander("tools/call", {"name": "RunPythonTest", "arguments": {
        "targets": ["test_mixte.py"], "parallel": "off", "cwd": "jetable"}})
    client.fermer()
    return client, init, liste, appel


def _verifier(client: ClientMcp, init: dict, liste: dict, appel: dict) -> str:
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["capabilities"] == {"tools": {}}
    noms = {o["name"]: o for o in liste["result"]["tools"]}
    assert set(noms) == {"RunPythonTest", "TestStatus"}
    assert "cwd" in noms["TestStatus"]["inputSchema"]["properties"]
    resultat = appel["result"]
    texte = resultat["content"][0]["text"]
    assert resultat["isError"] is False, texte  # des tests rouges ne sont pas une erreur d'outil
    assert "1 failed" in texte and "2 passed" in texte, texte
    assert "test_rouge" in texte and "attendu rouge" in texte
    for ligne in client.lignes:  # rien d'autre que du JSON-RPC sur stdout
        assert json.loads(ligne)["jsonrpc"] == "2.0", ligne
    return texte


def test_claude_code_lance_ses_tests_par_le_demon_prive(demon, tmp_path):
    """Avec le démon de la machine (ici privé, cf. fixture `demon`), le run passe par sa file
    et le rapport le dit ; PYTHONHOME du lanceur n'atteint pas le pytest du projet."""
    texte = _verifier(*_dialogue_complet(tmp_path))
    assert "testd job" in texte


def test_claude_code_lance_ses_tests_sans_demon(tmp_path):
    """`BZ_TESTD=0` : chemin direct, même rapport compact."""
    texte = _verifier(*_dialogue_complet(tmp_path, BZ_TESTD="0"))
    assert "testd" not in texte


def test_version_inconnue_methode_inconnue_et_ping(tmp_path):
    """Flux ouvert par un BOM (tube PowerShell) et version de protocole non prise en charge :
    le serveur répond avec la sienne ; une méthode inconnue rend une erreur JSON-RPC ; ping répond."""
    client = ClientMcp(tmp_path, tmp_path / "stderr.txt", BZ_TESTD_HOME=str(tmp_path / "testd_home"))
    client.process.stdin.write("﻿")
    init = client.demander("initialize", {"protocolVersion": "1999-01-01"})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert client.demander("ping")["result"] == {}
    assert client.demander("resources/list")["error"]["code"] == -32601
    absent = client.demander("tools/call", {"name": "TestStatus", "arguments": {
        "job_id": "x", "cwd": "nulle_part"}})
    assert absent["result"]["isError"] is True
    client.fermer()
    assert (tmp_path / "testd_home" / "mcp.log").read_text(encoding="utf-8").count("initialize") == 1
