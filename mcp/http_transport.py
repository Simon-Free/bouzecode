# [desc] HTTP and SSE transport implementation for communicating with MCP servers. [/desc]
"""HTTP and SSE transports for MCP servers."""
from __future__ import annotations

import json
import threading
from typing import Dict, Optional

from .types import MCPServerConfig, MCPTransport, make_notification, make_request


class HttpTransport:
    """Streamable-HTTP or SSE transport.

    SSE: sends messages via POST to the session endpoint; reads replies from
    the SSE stream. HTTP: stateless POST+response.
    """

    def __init__(self, config: MCPServerConfig):
        self._config = config
        self._session_url: Optional[str] = None
        self._lock = threading.Lock()
        self._next_id = 1
        self._client = None
        self._sse_thread: Optional[threading.Thread] = None
        self._sse_pending: Dict[int, dict] = {}
        self._running = False

    def _get_client(self):
        if self._client is None:
            try:
                import httpx
                self._client = httpx.Client(
                    headers=self._config.headers,
                    timeout=self._config.timeout,
                    follow_redirects=True,
                )
            except ImportError:
                raise RuntimeError("httpx is required for HTTP/SSE MCP transport: pip install httpx")
        return self._client

    def start(self) -> None:
        if self._config.transport == MCPTransport.SSE:
            self._start_sse()
        else:
            self._session_url = self._config.url

    def _start_sse(self) -> None:
        client = self._get_client()
        self._running = True

        endpoint_event = threading.Event()
        endpoint_holder: dict = {"url": None, "error": None}

        def _sse_reader():
            try:
                with client.stream("GET", self._config.url) as resp:
                    resp.raise_for_status()
                    event_type = None
                    for line in resp.iter_lines():
                        if not self._running:
                            break
                        if line.startswith("event:"):
                            event_type = line[6:].strip()
                        elif line.startswith("data:"):
                            data = line[5:].strip()
                            if event_type == "endpoint":
                                base = self._config.url.rsplit("/sse", 1)[0]
                                session_url = data if data.startswith("http") else base + data
                                endpoint_holder["url"] = session_url
                                self._session_url = session_url
                                endpoint_event.set()
                            elif event_type == "message":
                                try:
                                    msg = json.loads(data)
                                    msg_id = msg.get("id")
                                    if msg_id is not None and msg_id in self._sse_pending:
                                        holder = self._sse_pending[msg_id]
                                        holder["result"] = msg
                                        holder["event"].set()
                                except Exception:
                                    pass
            except Exception as e:
                endpoint_holder["error"] = str(e)
                endpoint_event.set()

        self._sse_thread = threading.Thread(target=_sse_reader, daemon=True)
        self._sse_thread.start()
        endpoint_event.wait(timeout=10)
        if endpoint_holder.get("error"):
            raise RuntimeError(f"SSE connect failed: {endpoint_holder['error']}")
        if not self._session_url:
            raise RuntimeError("SSE server did not send 'endpoint' event")

    def request(self, method: str, params: Optional[dict] = None, timeout: Optional[int] = None) -> dict:
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
        msg = make_request(method, params, req_id)
        client = self._get_client()
        wait_secs = timeout or self._config.timeout

        if self._config.transport == MCPTransport.SSE:
            event = threading.Event()
            holder: dict = {"event": event, "result": None}
            self._sse_pending[req_id] = holder
            client.post(self._session_url, json=msg)
            event.wait(timeout=wait_secs)
            self._sse_pending.pop(req_id, None)
            result = holder["result"]
        else:
            resp = client.post(self._session_url or self._config.url, json=msg, timeout=wait_secs)
            resp.raise_for_status()
            result = resp.json()

        if result is None:
            raise TimeoutError(f"MCP server '{self._config.name}' timed out on '{method}'")
        if "error" in result:
            err = result["error"]
            raise RuntimeError(f"MCP error {err.get('code')}: {err.get('message')}")
        return result.get("result", {})

    def notify(self, method: str, params: Optional[dict] = None) -> None:
        client = self._get_client()
        msg = make_notification(method, params)
        url = self._session_url or self._config.url
        try:
            client.post(url, json=msg)
        except Exception:
            pass

    def stop(self) -> None:
        self._running = False
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    @property
    def alive(self) -> bool:
        return self._session_url is not None or self._config.transport == MCPTransport.HTTP
