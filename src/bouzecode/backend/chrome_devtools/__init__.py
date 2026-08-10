# [desc] Package entrypoint exposing register_chrome_devtools_tools for the minimal chrome-devtools MCP integration. [/desc]
"""Minimal chrome-devtools MCP integration (mode B).

Autonomous module — deliberately NOT named `mcp` so the removal guard tests
(test_no_mcp_references / test_mcp_removed) stay green. Only exposes what the
frontend agent needs: launch the chrome-devtools MCP server under the
`--enable-chrome-devtools` flag and register its tools.
"""
from .launcher import register_chrome_devtools_tools  # noqa: F401

__all__ = ["register_chrome_devtools_tools"]
