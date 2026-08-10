# [desc] Backward-compatibility shim re-exporting transport, client, and manager classes. [/desc]
"""Backward-compat shim. Real implementation in stdio_transport / http_transport / mcp_client / manager."""
from .stdio_transport import StdioTransport  # noqa: F401
from .http_transport import HttpTransport    # noqa: F401
from .mcp_client import MCPClient            # noqa: F401
from .manager import MCPManager, get_mcp_manager  # noqa: F401
