# [desc] Manages multiple MCP server connections, tool discovery, and qualified tool dispatch. [/desc]
"""MCPManager: multi-server lifecycle + qualified tool dispatch."""
from __future__ import annotations

from typing import Dict, List, Optional

from .types import MCPServerConfig, MCPServerState, MCPTool
from .mcp_client import MCPClient


class MCPManager:
    """Singleton that manages all configured MCP server connections."""

    def __init__(self):
        self._clients: Dict[str, MCPClient] = {}

    def add_server(self, config: MCPServerConfig) -> MCPClient:
        if config.name in self._clients:
            try:
                self._clients[config.name].disconnect()
            except Exception:
                pass
        client = MCPClient(config)
        self._clients[config.name] = client
        return client

    def connect_all(self) -> Dict[str, Optional[str]]:
        errors: Dict[str, Optional[str]] = {}
        for name, client in self._clients.items():
            if client.config.disabled:
                errors[name] = "disabled"
                continue
            try:
                client.connect()
                client.list_tools()
                errors[name] = None
            except Exception as e:
                errors[name] = str(e)
        return errors

    def connect_server(self, name: str) -> MCPClient:
        client = self._clients.get(name)
        if client is None:
            raise KeyError(f"MCP server '{name}' not configured")
        if client.state != MCPServerState.CONNECTED:
            client.connect()
            client.list_tools()
        return client

    def all_tools(self) -> List[MCPTool]:
        tools: List[MCPTool] = []
        for client in self._clients.values():
            if client.state == MCPServerState.CONNECTED:
                tools.extend(client._tools)
        return tools

    def call_tool(self, qualified_name: str, arguments: dict) -> str:
        parts = qualified_name.split("__", 2)
        if len(parts) != 3 or parts[0] != "mcp":
            raise ValueError(f"Invalid MCP tool name: {qualified_name}")
        server_name = parts[1]
        tool_name = parts[2]
        client = self._clients.get(server_name)
        if client is None:
            raise RuntimeError(f"MCP server '{server_name}' not configured")
        if not client.alive:
            client.reconnect()
            client.list_tools()
        original_name = tool_name
        for t in client._tools:
            if t.qualified_name == qualified_name:
                original_name = t.tool_name
                break
        return client.call_tool(original_name, arguments)

    def list_servers(self) -> List[MCPClient]:
        return list(self._clients.values())

    def disconnect_all(self) -> None:
        for client in self._clients.values():
            try:
                client.disconnect()
            except Exception:
                pass

    def reload_server(self, name: str) -> None:
        client = self._clients.get(name)
        if client:
            client.reconnect()
            client.list_tools()


_manager: Optional[MCPManager] = None


def get_mcp_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager
