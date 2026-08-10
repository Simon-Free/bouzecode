# [desc] Parses bouzecode session text into structured blocks (AssistantText, UserMessage, ToolCall, ToolResult). [/desc]
# [desc] Parses bouzecode session text into structured blocks (AssistantText, UserMessage, ToolCall, ToolResult).
"""Parse bouzecode session text into structured blocks."""
import re
from dataclasses import dataclass, field

_TOOL_USE_RE = re.compile(
    r'<tool_use\s+name="([^"]+)"\s+id="([^"]+)">(.*?)</tool_use>',
    re.DOTALL,
)
_TOOL_RESULT_RE = re.compile(
    r'<tool_result\s+id="([^"]+)">(.*?)</tool_result>',
    re.DOTALL,
)
_PARAM_RE = re.compile(
    r'<param\s+name="([^"]+)">(.*?)</param>',
    re.DOTALL,
)


@dataclass
class UserMessage:
    content: str


@dataclass
class AssistantText:
    content: str


@dataclass
class ToolCall:
    name: str
    call_id: str
    params: dict[str, str] = field(default_factory=dict)


@dataclass
class ToolResult:
    call_id: str
    content: str
    tool_name: str = ""


Block = UserMessage | AssistantText | ToolCall | ToolResult


def _strip_cdata(text: str) -> str:
    text = text.strip()
    cdata_end = "]]" + ">"
    if text.startswith("<![CDATA[") and text.endswith(cdata_end):
        return text[9:-3]
    return text


def _parse_params(body: str) -> dict[str, str]:
    return {m.group(1): _strip_cdata(m.group(2)) for m in _PARAM_RE.finditer(body)}


def parse_session(text: str) -> list[Block]:
    """Parse raw session text into a sequence of typed blocks."""
    markers: list[tuple[int, int, str, re.Match]] = []
    for m in _TOOL_USE_RE.finditer(text):
        markers.append((m.start(), m.end(), "use", m))
    for m in _TOOL_RESULT_RE.finditer(text):
        markers.append((m.start(), m.end(), "result", m))
    markers.sort(key=lambda x: x[0])

    blocks: list[Block] = []
    pos = 0
    for start, end, kind, m in markers:
        if start > pos:
            assistant_text = text[pos:start].strip()
            if assistant_text:
                blocks.append(AssistantText(content=assistant_text))
        if kind == "use":
            blocks.append(ToolCall(
                name=m.group(1),
                call_id=m.group(2),
                params=_parse_params(m.group(3)),
            ))
        else:
            blocks.append(ToolResult(
                call_id=m.group(1),
                content=_strip_cdata(m.group(2)),
            ))
        pos = end

    if pos < len(text):
        trailing = text[pos:].strip()
        if trailing:
            blocks.append(AssistantText(content=trailing))
    return blocks
