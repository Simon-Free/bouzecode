# [desc] Faux LLM Anthropic (/v1/messages, SSE) sur un vrai socket local, qui REFUSE chaque requête (stop_reason `refusal`, aucun contenu) — le refus du filtre de contenu vu par un vrai process bouzecode. [/desc]
"""Un serveur HTTP minimal (stdlib) : chaque POST rend un flux SSE Anthropic sans aucun bloc de
contenu et clos sur `stop_reason: "refusal"`, ce que renvoie le fournisseur quand son filtre
refuse la consigne. Sert aux tests qui lancent le VRAI CLI (`python -m bouzecode -p …`) et
vérifient sa sortie (code, fiche de clôture), en local comme dans un paquet joué par vm_runner.

`environnement_cli(llm, home)` : env d'un process bouzecode pointé sur ce faux LLM, avec un
profil jetable (HOME et USERPROFILE) — jamais le `~/.bouzecode` réel. `script_vm(llm, home)` :
la commande d'un paquet Rundeck qui lance ce même CLI comme le fait `lancement.commande_agent`."""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread  # serveur de fond, pas un test de concurrence

SOURCES_BOUZECODE = Path(__file__).resolve().parents[3]
MODELE = "claude-opus-5"
PROXYS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy")


def _evenement(nom: str, donnees: dict) -> bytes:
    return f"event: {nom}\ndata: {json.dumps(donnees)}\n\n".encode("utf-8")


def flux_de_refus(modele: str) -> bytes:
    usage = {"input_tokens": 10, "output_tokens": 1, "cache_read_input_tokens": 0,
             "cache_creation_input_tokens": 0}
    return b"".join([
        _evenement("message_start", {"type": "message_start", "message": {
            "id": "msg_refus", "type": "message", "role": "assistant", "content": [],
            "model": modele, "stop_reason": None, "stop_sequence": None, "usage": usage}}),
        _evenement("message_delta", {"type": "message_delta",
                                     "delta": {"stop_reason": "refusal", "stop_sequence": None},
                                     "usage": {"output_tokens": 1}}),
        _evenement("message_stop", {"type": "message_stop"}),
    ])


class _Refuseur(BaseHTTPRequestHandler):
    def log_message(self, *arguments):
        pass

    def do_POST(self):  # noqa: N802 — nommage de http.server
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self.server.requetes.append(corps)
        donnees = flux_de_refus(str(corps.get("model") or MODELE))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(donnees)))
        self.end_headers()
        self.wfile.write(donnees)


class FauxLlmRefus:
    """`with FauxLlmRefus() as llm:` — `llm.url` pour ANTHROPIC_BASE_URL, `llm.requetes` reçues."""

    def __init__(self) -> None:
        self._serveur = ThreadingHTTPServer(("127.0.0.1", 0), _Refuseur)
        self._serveur.daemon_threads = True
        self._serveur.requetes = []

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._serveur.server_address[1]}"

    @property
    def requetes(self) -> list[dict]:
        return self._serveur.requetes

    def __enter__(self) -> "FauxLlmRefus":
        Thread(target=self._serveur.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._serveur.shutdown()
        self._serveur.server_close()


def variables_cli(llm: FauxLlmRefus, home: Path) -> dict[str, str]:
    """Ce qu'il faut poser sur l'env d'un process bouzecode pour le pointer sur le faux LLM."""
    home.mkdir(parents=True, exist_ok=True)
    return {"HOME": str(home), "USERPROFILE": str(home), "ANTHROPIC_BASE_URL": llm.url,
            "ANTHROPIC_API_KEY": "cle-factice", "ANTHROPIC_AUTH_TOKEN": "cle-factice",
            "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
            "PYTHONPATH": str(SOURCES_BOUZECODE), "PYTHONIOENCODING": "utf-8"}


def sans_proxy(env: dict[str, str]) -> dict[str, str]:
    return {cle: valeur for cle, valeur in env.items() if cle not in PROXYS}


def environnement_cli(llm: FauxLlmRefus, home: Path) -> dict[str, str]:
    """Env d'un `python -m bouzecode` qui ne parle qu'au faux LLM, dans un profil jetable."""
    return {**sans_proxy(dict(os.environ)), **variables_cli(llm, home)}


def commande_cli(result_file: str, *options: str, consigne: str = "Ajoute b.txt") -> list[str]:
    return [sys.executable, "-m", "bouzecode", "-p", "--accept-all", "-m", MODELE,
            "--result-file", result_file, *options, consigne]


def script_vm(llm: FauxLlmRefus, home: Path, dossier: Path) -> str:
    """Commande de paquet qui joue `bouzecode -p --result-file "$BZ_RESULTAT/reponse.md"` contre
    le faux LLM (cf. `lancement.commande_agent`) et sort avec SON code."""
    script = dossier / "agent_vm_refus.py"
    script.write_text(
        "import json, os, subprocess, sys\n"
        f"proxys = {list(PROXYS)!r}\n"
        "env = {k: v for k, v in os.environ.items() if k not in proxys}\n"
        f"env.update(json.loads({json.dumps(json.dumps(variables_cli(llm, home)))}))\n"
        "reponse = os.path.join(os.environ['BZ_RESULTAT'], 'reponse.md')\n"
        f"commande = json.loads({json.dumps(json.dumps(commande_cli('REPONSE')))})\n"
        "commande[commande.index('REPONSE')] = reponse\n"
        "sys.exit(subprocess.run(commande, env=env, timeout=120).returncode)\n",
        encoding="utf-8")
    return f'"{sys.executable}" "{script}"'
