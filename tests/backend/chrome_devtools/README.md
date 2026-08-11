# chrome_devtools/

## Purpose
Tests of `bouzecode.backend.chrome_devtools.launcher` — declaring the browser tools in
`core.tool_registry`, starting the MCP server lazily, remembering its manifest, and
keeping one transport per thread. The server is real, not mocked: a stdio JSON-RPC
subprocess started from this folder.

## Usage
- `fake_mcp_server.py` — `main()`, a minimal stdio MCP server answering `initialize` / `tools/list` / `tools/call` and exposing one `navigate` tool.
- `test_chrome_devtools.py` — the eager flag declares tools without starting the server; no manifest means nothing declared and nothing launched; the manifest is memorised on the first real start; lazy enable ignores the flag and is idempotent per thread; using a tool starts the browser on its own; shutdown removes the tools and kills the server, while a declared capability survives a stop; parallel threads each get their own server and one shutdown leaves the others alive.
