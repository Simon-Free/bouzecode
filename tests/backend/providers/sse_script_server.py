# [desc] Real local HTTP server replaying scripted, timed SSE lines (chunked) for chat/completions stream tests. [/desc]
"""Faux endpoint chat/completions RÉEL : un vrai socket, du vrai `Transfer-Encoding: chunked`,
et des lignes SSE émises avec un délai — ce que les doubles en mémoire ne savent pas faire
(un keep-alive qui arrive, puis rien, sur un socket qui reste ouvert).

Chaque POST consomme le script suivant : une liste de ``(délai_s, ligne)``. Les corps reçus
sont gardés dans ``request_bodies`` pour comparer une relance à l'originale."""
from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


class _ScriptedHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802 - http.server naming
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.request_bodies.append(json.loads(body))
        script = self.server.scripts.pop(0)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            for delay_s, line in script:
                time.sleep(delay_s)
                self._write_chunk(f"{line}\n".encode("utf-8"))
            self._write_chunk(b"")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True  # the client hung up (watchdog): stop writing

    def _write_chunk(self, data: bytes) -> None:
        self.wfile.write(f"{len(data):x}\r\n".encode("ascii") + data + b"\r\n")
        self.wfile.flush()

    def log_message(self, *args):
        pass


class SseScriptServer:
    def __init__(self, scripts: list[list[tuple[float, str]]]):
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _ScriptedHandler)
        self._server.daemon_threads = True
        self._server.block_on_close = False
        self._server.scripts = list(scripts)
        self._server.request_bodies = []
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    @property
    def request_bodies(self) -> list[dict]:
        return self._server.request_bodies

    def __enter__(self) -> "SseScriptServer":
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._server.shutdown()
        self._server.server_close()
