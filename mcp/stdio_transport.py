# [desc] Implements JSON-RPC communication with MCP servers over subprocess stdin/stdout using threads. [/desc]
"""Bidirectional JSON-RPC over a subprocess's stdin/stdout."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from typing import Dict, List, Optional

from .types import MCPServerConfig, make_notification, make_request


class StdioTransport:
    """Newline-delimited JSON-RPC over subprocess stdin/stdout.

    Responses are matched to requests by 'id'.
    """

    def __init__(self, config: MCPServerConfig):
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
        cmd = [self._config.command] + list(self._config.args or [])
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
