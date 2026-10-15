# [desc] Faux LLM Anthropic (/v1/messages, SSE) sur un vrai socket local qui JOUE un script de réponses texte (prose, ou appels d'outils XML comme FinalAnswer) — le vrai CLI `-p` face à un modèle qui répond en prose. [/desc]
"""Même serveur que `faux_llm_refus` (stdlib, vrai socket), mais chaque POST rend la réponse
suivante d'un script : un flux SSE Anthropic à un bloc texte, clos sur `end_turn`. Le modèle
`claude-opus-5` parle le protocole d'outils XML : un `<tool_use name="FinalAnswer">` dans le
texte EST un appel d'outil. Au-delà du script, la dernière réponse est rejouée (prose obstinée).

`environnement_cli`, `commande_cli` et `script_vm` de `faux_llm_refus` s'appliquent tels quels :
ils ne lisent que `llm.url`."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .faux_llm_refus import MODELE, FauxLlmRefus, _evenement

METHODOLOGY = '<tool_use name="Methodology" id="m1"><param name="content">fait</param></tool_use>'


def final_answer(reponse: str) -> str:
    """Le texte d'un tour qui clôt par FinalAnswer (Methodology jointe : pas de récupération)."""
    return (f'{METHODOLOGY}\n<tool_use name="FinalAnswer" id="f1"><param name="answer">{reponse}'
            '</param><param name="taches_terminees">[]</param>'
            '<param name="taches_restantes">[]</param></tool_use>')


def flux_texte(modele: str, texte: str) -> bytes:
    usage = {"input_tokens": 10, "output_tokens": 0, "cache_read_input_tokens": 0,
             "cache_creation_input_tokens": 0}
    return b"".join([
        _evenement("message_start", {"type": "message_start", "message": {
            "id": "msg_script", "type": "message", "role": "assistant", "content": [],
            "model": modele, "stop_reason": None, "stop_sequence": None, "usage": usage}}),
        _evenement("content_block_start", {"type": "content_block_start", "index": 0,
                                           "content_block": {"type": "text", "text": ""}}),
        _evenement("content_block_delta", {"type": "content_block_delta", "index": 0,
                                           "delta": {"type": "text_delta", "text": texte}}),
        _evenement("content_block_stop", {"type": "content_block_stop", "index": 0}),
        _evenement("message_delta", {"type": "message_delta",
                                     "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                     "usage": {"output_tokens": max(1, len(texte) // 4)}}),
        _evenement("message_stop", {"type": "message_stop"}),
    ])


class _Scripte(BaseHTTPRequestHandler):
    def log_message(self, *arguments):
        pass

    def do_POST(self):  # noqa: N802 — nommage de http.server
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self.server.requetes.append(corps)
        script = self.server.reponses
        texte = script[min(len(self.server.requetes), len(script)) - 1]
        donnees = flux_texte(str(corps.get("model") or MODELE), texte)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(donnees)))
        self.end_headers()
        self.wfile.write(donnees)


class FauxLlmScripte(FauxLlmRefus):
    """`with FauxLlmScripte(["prose", final_answer("fait")]) as llm:` — réponses dans l'ordre."""

    def __init__(self, reponses: list[str]) -> None:
        self._serveur = ThreadingHTTPServer(("127.0.0.1", 0), _Scripte)
        self._serveur.daemon_threads = True
        self._serveur.requetes = []
        self._serveur.reponses = list(reponses)
