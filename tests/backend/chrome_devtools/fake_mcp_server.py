"""A real (not mocked) minimal stdio MCP server for tests.

Reads newline-delimited JSON-RPC from stdin, answers initialize / tools/list /
tools/call. Exposes a single tool `navigate`.
"""
import json
import os
import sys


def _send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        method = msg.get("method")
        req_id = msg.get("id")

        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-chrome-devtools", "version": "0.0.1"},
            }})
        elif method == "notifications/initialized":
            pass  # notification, no response
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": [
                {
                    "name": "navigate",
                    "description": "Navigate the browser to a URL.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"url": {"type": "string"}},
                        "required": ["url"],
                    },
                    "annotations": {"readOnlyHint": False},
                },
            ]}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            args = params.get("arguments") or {}
            url = args.get("url", "")
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": f"navigated to {url} [pid={os.getpid()}]"}],
                "isError": False,
            }})
        elif req_id is not None:
            _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "method not found"}})


if __name__ == "__main__":
    main()
