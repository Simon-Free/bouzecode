# [desc] Generates demo.html from a hardcoded example bouzecode session. [/desc]
# [desc] Generates demo.html from a hardcoded example bouzecode session.
"""Generate demo.html from a hardcoded example session."""
from pathlib import Path

from .parser import parse_session
from .renderer import render_html

_EXAMPLE_SESSION = """\
I'll read the config file and then make some changes.

<tool_use name="Read" id="r1"><param name="file_path">/app/config.py</param></tool_use>

<tool_result id="r1">DEBUG = False
PORT = 8080
HOST = "localhost"</tool_result>

The config looks good. Let me update the **port** to `9090`.

<tool_use name="Edit" id="e1"><param name="file_path">/app/config.py</param><param name="old_string">PORT = 8080
HOST = "localhost"</param><param name="new_string">PORT = 9090
HOST = "0.0.0.0"</param></tool_use>

<tool_result id="e1">Applied edit to /app/config.py</tool_result>

Now let me create a new utility module.

<tool_use name="Write" id="w1"><param name="file_path">/app/utils.py</param><param name="content">def greet(name: str) -> str:
    return f"Hello, {name}!"


def add(a: int, b: int) -> int:
    return a + b
</param></tool_use>

<tool_result id="w1">Created /app/utils.py (6 lines)</tool_result>

## Summary

All changes applied successfully:
- **Port** updated from `8080` to `9090`
- **Host** changed to bind all interfaces
- New `utils.py` module created with helper functions
"""


def main() -> None:
    blocks = parse_session(_EXAMPLE_SESSION)
    html_content = render_html(blocks, finished=True)
    out = Path(__file__).parent / "demo.html"
    out.write_text(html_content, encoding="utf-8")
    print(f"Wrote {out} ({len(html_content)} bytes, {len(blocks)} blocks)")


if __name__ == "__main__":
    main()
