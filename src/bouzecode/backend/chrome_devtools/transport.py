# [desc] Self-contained JSON-RPC-over-stdio transport (StdioTransport) for talking to an MCP server subprocess. [/desc]
"""Bidirectional JSON-RPC over a subprocess's stdin/stdout (stdio only).

Self-contained: the minimal server-config and JSON-RPC helpers are inlined here
so this module has no dependency on any deleted `mcp` package.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ServerConfig:
    """Minimal stdio MCP server config."""
    name: str
    command: str = ""
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    timeout: int = 30


def make_request(method: str, params: Optional[dict], req_id: int) -> dict:
    msg: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def make_notification(method: str, params: Optional[dict] = None) -> dict:
    msg: dict = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    return msg


class StdioTransport:
    """Newline-delimited JSON-RPC over subprocess stdin/stdout.

    Responses are matched to requests by 'id'.
    """

    def __init__(self, config: ServerConfig):
        self._config = config
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._next_id = 1
        self._pending: Dict[int, dict] = {}
        self._reader: Optional[threading.Thread] = None
        self._stderr_reader: Optional[threading.Thread] = None
        self._running = False
        self._stderr_lines: List[str] = []

    def start(self) -> None:
        env = {**os.environ, **(self._config.env or {})}
        # Windows: resolve bare names like "npx" to their .cmd/.exe shim via PATHEXT.
        # CreateProcess won't apply PATHEXT itself, so "npx" alone fails with WinError 2.
        resolved_command = shutil.which(self._config.command) or self._config.command
        cmd = [resolved_command] + list(self._config.args or [])
        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(target=self._stderr_loop, daemon=True)
        self._stderr_reader.start()

    def _read_loop(self) -> None:
        while self._running and self._process:
            try:
                raw = self._process.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                msg = json.loads(line)
            except Exception:
                continue
            msg_id = msg.get("id")
            if msg_id is not None and msg_id in self._pending:
                holder = self._pending[msg_id]
                holder["result"] = msg
                holder["event"].set()

    def _stderr_loop(self) -> None:
        while self._running and self._process:
            try:
                raw = self._process.stderr.readline()
                if not raw:
                    break
                self._stderr_lines.append(raw.decode("utf-8", errors="replace").rstrip())
            except Exception:
                break

    def _send_raw(self, msg: dict) -> None:
        line = (json.dumps(msg) + "\n").encode("utf-8")
        with self._lock:
            self._process.stdin.write(line)
            self._process.stdin.flush()

    def request(self, method: str, params: Optional[dict] = None, timeout: Optional[int] = None) -> dict:
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
        event = threading.Event()
        holder: dict = {"event": event, "result": None}
        self._pending[req_id] = holder
        self._send_raw(make_request(method, params, req_id))
        event.wait(timeout=timeout or self._config.timeout)
        self._pending.pop(req_id, None)
        result = holder["result"]
        if result is None:
            raise TimeoutError(f"MCP server '{self._config.name}' timed out on '{method}'")
        if "error" in result:
            err = result["error"]
            raise RuntimeError(f"MCP error {err.get('code')}: {err.get('message')}")
        return result.get("result", {})

    def notify(self, method: str, params: Optional[dict] = None) -> None:
        self._send_raw(make_notification(method, params))

    def stop(self) -> None:
        self._running = False
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                pass
            self._process = None

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def stderr_output(self) -> str:
        return "\n".join(self._stderr_lines[-20:])
