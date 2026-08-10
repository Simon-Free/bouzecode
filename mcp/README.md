# mcp/

## Purpose
Model Context Protocol client: discovers tools from configured MCP servers (stdio / SSE / HTTP) and exposes them as agent tools named `mcp__<server>__<tool>`.

## Usage
- `types.py` — `MCPServerConfig`, `MCPTool`, `MCPServerState`, `MCPTransport`, `INIT_PARAMS`, `make_request()`, `make_notification()`
- `stdio_transport.py` — `StdioTransport` (JSON-RPC over subprocess stdio)
- `http_transport.py` — `HttpTransport` (SSE + plain HTTP)
- `mcp_client.py` — `MCPClient` (connect, list_tools, call_tool)
- `manager.py` — `MCPManager`, `get_mcp_manager()` (multi-server lifecycle)
- `client.py` — thin backward-compat shim re-exporting all of the above
- `config.py` — `load_mcp_configs()`, `save_user_mcp_config()`, etc.
- `tools.py` — `initialize_mcp()`, `reload_mcp()`, `refresh_server()` (agent tool wiring)
