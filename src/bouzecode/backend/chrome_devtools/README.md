# chrome_devtools/

## Purpose
A self-contained MCP client for a browser devtools server. It spawns the server as a subprocess (one browser per agent thread), lists the tools it exposes, and registers each of them in the tool registry so the model can drive a page.

## Usage
- `transport.py` — `StdioTransport`: JSON-RPC over the subprocess stdin/stdout (initialize, request/response correlation, notifications, shutdown). `ServerConfig`, `make_request`, `make_notification`
- `launcher.py` — `register_chrome_devtools_tools(command, args)` starts a transport and registers the listed browser tools, returning how many; `enable_chrome_devtools` / `shutdown_chrome_devtools` are the per-thread lifecycle, `shutdown_all` tears down every transport. `is_active()` reports whether the current thread has one. `register_bootstrap_tools()` registers the two always-present switches named in `BOOTSTRAP_TOOL_NAMES` (`EnableChromeDevtools`, `DisableChromeDevtools`), so the browser tools cost nothing until an agent asks for them. The tool list is cached to a manifest on disk between runs. `SERVER_NAME`, `PROTOCOL_VERSION`, `INIT_PARAMS`
- `__init__.py` re-exports `register_chrome_devtools_tools`
