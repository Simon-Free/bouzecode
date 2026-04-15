# [desc] High-level MCP client managing server connection lifecycle, tool discovery, and tool invocation. [/desc]
"""High-level MCPClient: connect/handshake, list_tools, call_tool."""
from __future__ import annotations

from typing import Any, List, Optional

from .types import (
    MCPServerConfig, MCPServerState, MCPTool, MCPTransport, INIT_PARAMS,
)
from .stdio_transport import StdioTransport
from .http_transport import HttpTransport


class MCPClient:
    """Manages the lifecycle of one MCP server connection."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.state = MCPServerState.DISCONNECTED
        self._transport: Optional[Any] = None
        self._server_info: dict = {}
        self._capabilities: dict = {}
        self._tools: List[MCPTool] = []
        self._error: str = ""

    def connect(self) -> None:
        if self.state == MCPServerState.CONNECTED:
            return
        self.state = MCPServerState.CONNECTING
        self._error = ""
        try:
            self._transport = self._make_transport()
            self._transport.start()
            self._handshake()
            self.state = MCPServerState.CONNECTED
        except Exception as e:
            self.state = MCPServerState.ERROR
            self._error = str(e)
            raise

    def _make_transport(self):
        t = self.config.transport
        if t == MCPTransport.STDIO:
            return StdioTransport(self.config)
        if t in (MCPTransport.SSE, MCPTransport.HTTP):
            return HttpTransport(self.config)
        raise ValueError(f"Unsupported MCP transport: {t}")

    def _handshake(self) -> None:
        result = self._transport.request("initialize", INIT_PARAMS, timeout=15)
        self._server_info = result.get("serverInfo", {})
        self._capabilities = result.get("capabilities", {})
        self._transport.notify("notifications/initialized")

    def disconnect(self) -> None:
        if self._transport:
            self._transport.stop()
            self._transport = None
        self.state = MCPServerState.DISCONNECTED

    def reconnect(self) -> None:
        self.disconnect()
        self.connect()

    @property
    def alive(self) -> bool:
        return (
            self.state == MCPServerState.CONNECTED
            and self._transport is not None
            and self._transport.alive
        )

    def list_tools(self) -> List[MCPTool]:
        if self.state != MCPServerState.CONNECTED:
            raise RuntimeError(f"MCP server '{self.config.name}' is not connected")
        if "tools" not in self._capabilities:
            self._tools = []
            return self._tools
        result = self._transport.request("tools/list", timeout=15)
        raw_tools = result.get("tools", [])
        self._tools = [self._parse_tool(t) for t in raw_tools]
        return self._tools

    def _parse_tool(self, raw: dict) -> MCPTool:
        tool_name = raw.get("name", "")
        qualified = f"mcp__{self.config.name}__{tool_name}"
        qualified = "".join(c if c.isalnum() or c == "_" else "_" for c in qualified)
        annotations = raw.get("annotations", {})
        read_only = bool(annotations.get("readOnlyHint", False))
        schema = raw.get("inputSchema", {"type": "object", "properties": {}})
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        return MCPTool(
            server_name=self.config.name,
            tool_name=tool_name,
            qualified_name=qualified,
            description=raw.get("description", ""),
            input_schema=schema,
            read_only=read_only,
        )

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        if self.state != MCPServerState.CONNECTED:
            raise RuntimeError(f"MCP server '{self.config.name}' is not connected")
        params = {"name": tool_name, "arguments": arguments}
        result = self._transport.request("tools/call", params, timeout=self.config.timeout)
        is_error = result.get("isError", False)
        content = result.get("content", [])
        parts: List[str] = []
        for block in content:
            btype = block.get("type", "")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "image":
                parts.append(f"[image: {block.get('mimeType', 'unknown')}]")
            elif btype == "resource":
                res = block.get("resource", {})
                parts.append(f"[resource: {res.get('uri', '')}]")
        text = "\n".join(parts) if parts else str(result)
        if is_error:
            return f"[MCP tool error]\n{text}"
        return text

    def status_line(self) -> str:
        icon = {"connected": "\u2713", "connecting": "\u2026", "disconnected": "\u25cb", "error": "\u2717"}.get(
            self.state.value, "?"
        )
        server = self._server_info.get("name", self.config.name)
        version = self._server_info.get("version", "")
        tool_count = len(self._tools)
        line = f"{icon} {self.config.name}"
        if server and server != self.config.name:
            line += f" ({server}"
            if version:
                line += f" v{version}"
            line += ")"
        if self.state == MCPServerState.CONNECTED:
            line += f"  [{tool_count} tool(s)]"
        if self.state == MCPServerState.ERROR:
            line += f"  error: {self._error}"
        return line
