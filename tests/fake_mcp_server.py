#!/usr/bin/env python3
"""Fake MCP server for testing — speaks JSON-RPC over stdin/stdout (stdio transport).

Supports:
- initialize → returns server info + capabilities
- notifications/initialized → no response (notification)
- tools/list → returns one tool: "echo"
- tools/call → echo tool returns the 'message' param as text content
"""
import json
import sys


def make_response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


TOOLS = [
    {
        "name": "echo",
        "description": "Echoes the input message back",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to echo"}
            },
            "required": ["message"],
        },
        "annotations": {"readOnlyHint": True},
    }
]


def handle_request(msg):
    """Process a JSON-RPC request and return a response dict, or None for notifications."""
    method = msg.get("method", "")
    req_id = msg.get("id")  # None for notifications
    params = msg.get("params", {})

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "fake-server", "version": "1.0.0"},
            "capabilities": {"tools": {}},
        }
        return make_response(req_id, result)

    elif method == "notifications/initialized":
        # Notification — no response
        return None

    elif method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "echo":
            message = arguments.get("message")
            if message is None:
                return make_response(req_id, {
                    "isError": True,
                    "content": [{"type": "text", "text": "Missing required parameter: message"}],
                })
            return make_response(req_id, {
                "content": [{"type": "text", "text": message}],
            })
        else:
            return make_error(req_id, -32601, f"Unknown tool: {tool_name}")

    else:
        if req_id is not None:
            return make_error(req_id, -32601, f"Method not found: {method}")
        return None


def main():
    """Main loop: read JSON-RPC messages from stdin, write responses to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = handle_request(msg)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
