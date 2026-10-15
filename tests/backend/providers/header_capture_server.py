"""Serveur HTTP local qui capture chemin + en-têtes des requêtes et répond comme l'API
Anthropic (/v1/messages, JSON) ou OpenAI-compatible (/chat/completions, SSE).

Module à part : les modules de test qui démarrent un thread sont marqués `timing`
(tests/auto_markers.py) et désélectionnés par défaut.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANTHROPIC_REPLY = {
    "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-test",
    "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
    "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
}
OPENAI_SSE = (
    'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"index":0,'
    '"delta":{"role":"assistant","content":"ok"},"finish_reason":null}]}\n\n'
    'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"index":0,'
    '"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1}}\n\n'
    "data: [DONE]\n\n"
)


class _Capture(BaseHTTPRequestHandler):
    captured: list = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        type(self).captured.append({"path": self.path, "headers": dict(self.headers)})
        if self.path.endswith("/chat/completions"):
            body = OPENAI_SSE.encode()
            ctype = "text/event-stream"
        else:
            body = json.dumps(ANTHROPIC_REPLY).encode()
            ctype = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class HeaderCaptureServer:
    """`with HeaderCaptureServer() as srv:` → srv.root (http://127.0.0.1:port), srv.captured."""

    def __init__(self) -> None:
        handler = type("Handler", (_Capture,), {"captured": []})
        self.captured: list = handler.captured
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.root = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self) -> "HeaderCaptureServer":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
