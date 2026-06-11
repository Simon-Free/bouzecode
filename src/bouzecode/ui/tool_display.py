# [desc] Formats and prints tool invocation start/end status with ANSI colors, diffs, and duration info. [/desc]
# [desc] Formats and prints tool invocation start/end status with ANSI colors, diffs, and duration info. [/desc]
import json
from .ansi import C, clr

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    _RICH_CONSOLE = Console()
except ImportError:
    _RICH_CONSOLE = None

_last_diffs: dict[str, str] = {}

# Synthetic tools the parser/registry emit for malformed input. Their result is
# always a diagnostic — render them as a failed tool call, never as success.
_ERROR_TOOL_NAMES = {"_XmlParseError", "_InvalidToolName", "_ToolArgsParseError"}


def _is_failure(name: str, result: str) -> bool:
    """True if a tool result should render as a failure (red ✗).

    The registry emits diagnostics prefixed 'ERROR'/'Error'/'Denied' (case
    varies), so the check is case-insensitive; synthetic error tools always fail.
    """
    if name in _ERROR_TOOL_NAMES:
        return True
    head = result.lstrip()[:6].lower()
    return head.startswith("error") or head.startswith("denied")


def render_diff(text: str):
    for line in text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            print(C["bold"] + line + C["reset"])
        elif line.startswith("+"):
            print(C["green"] + line + C["reset"])
        elif line.startswith("-"):
            print(C["red"] + line + C["reset"])
        elif line.startswith("@@"):
            print(C["cyan"] + line + C["reset"])
        else:
            print(line)

def _has_diff(text: str) -> bool:
    return "--- a/" in text and "+++ b/" in text


def _fmt_duration(seconds: float) -> str:
    if seconds < 1.0:
        return f"{int(seconds * 1000)}ms"
    if seconds < 60.0:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remaining = seconds - minutes * 60
    return f"{minutes}m{remaining:.0f}s"


def print_tool_start(name: str, inputs: dict, verbose: bool):
    if name == "WritePlan":
        content = inputs.get("content", "")
        print()
        print(clr("  Plan :", "bold", "cyan"))
        print()
        if _RICH_CONSOLE is not None:
            _RICH_CONSOLE.print(Panel(Markdown(content), border_style="cyan", padding=(0, 2)))
        else:
            for line in content.splitlines():
                print(f"    {line}")
        print()
        return
    desc = _tool_desc(name, inputs)
    print(clr(f"  \u2699  {desc}", "dim", "cyan"), flush=True)
    if verbose:
        print(clr(f"     inputs: {json.dumps(inputs, ensure_ascii=False)[:200]}", "dim"))


def print_tool_end(name: str, result: str, verbose: bool, duration: float = 0.0,
                    tool_id: str = "", inputs: dict | None = None):
    if name == "WritePlan":
        dur_str = f" [{_fmt_duration(duration)}]" if duration > 0 else ""
        print(clr(f"  \u2713 Plan saved{dur_str}", "dim", "green"), flush=True)
        return
    lines = result.count("\n") + 1
    size = len(result)
    dur_suffix = f" [{_fmt_duration(duration)}]" if duration > 0 else ""
    desc = _tool_desc(name, inputs) if inputs else name
    summary = f"{desc} \u2192 {lines} lines ({size} chars){dur_suffix}"
    if not _is_failure(name, result):
        if name in ("Edit", "Write") and _has_diff(result):
            parts = result.split("\n\n", 1)
            header = parts[0] if len(parts) == 2 else result.splitlines()[0]
            diff_text = parts[1] if len(parts) == 2 else ""
            added = sum(1 for l in diff_text.splitlines() if l.startswith("+") and not l.startswith("+++"))
            removed = sum(1 for l in diff_text.splitlines() if l.startswith("-") and not l.startswith("---"))
            fpath = ""
            for l in diff_text.splitlines():
                if l.startswith("--- a/"):
                    fpath = l[6:]
                    break
            if fpath and diff_text:
                _last_diffs[fpath] = diff_text
            print(clr(f"  \u2713 {header.split(chr(10))[0]}", "dim", "green"), flush=True)
            info_parts = []
            if added:
                info_parts.append(clr(f"+{added}", "green"))
            if removed:
                info_parts.append(clr(f"-{removed}", "red"))
            info_str = "/".join(info_parts) if info_parts else ""
            tail = f" {clr(dur_suffix.strip(), 'dim')}" if dur_suffix else ""
            print(f"     {info_str}  {clr('/diff to view', 'dim')}{tail}", flush=True)
        else:
            print(clr(f"  \u2713 {summary}", "dim", "green"), flush=True)
    else:
        print(clr(f"  \u2717 {result[:120]}", "dim", "red"), flush=True)
    if verbose and not result.startswith("Denied"):
        preview = result[:500] + ("\u2026" if len(result) > 500 else "")
        print(clr(f"     {preview.replace(chr(10), chr(10)+'     ')}", "dim"))


def _tool_desc(name: str, inputs: dict) -> str:
    if name == "Read":
        fp = inputs.get("file_path", "")
        sym = inputs.get("symbol")
        return f"Read({fp}, symbol={sym})" if sym else f"Read({fp})"
    if name == "Write":  return f"Write({inputs.get('file_path','')})"
    if name == "Edit":   return f"Edit({inputs.get('file_path','')})"
    if name == "Bash":   return f"Bash({inputs.get('command','')[:80]})"
    if name == "Glob":   return f"Glob({inputs.get('pattern','')})"
    if name == "Grep":   return f"Grep({inputs.get('pattern','')})"
    if name == "WebFetch":    return f"WebFetch({inputs.get('url','')[:60]})"
    if name == "WebSearch":   return f"WebSearch({inputs.get('query','')})"
    if name == "Agent":
        atype = inputs.get("subagent_type", "")
        aname = inputs.get("name", "")
        iso   = inputs.get("isolation", "")
        bg    = not inputs.get("wait", True)
        parts = []
        if atype:  parts.append(atype)
        if aname:  parts.append(f"name={aname}")
        if iso:    parts.append(f"isolation={iso}")
        if bg:     parts.append("background")
        suffix = f"({', '.join(parts)})" if parts else ""
        prompt_short = inputs.get("prompt", "")[:60]
        return f"Agent{suffix}: {prompt_short}"
    if name == "SendMessage":
        return f"SendMessage(to={inputs.get('to','')}: {inputs.get('message','')[:50]})"
    if name == "CheckAgentResult": return f"CheckAgentResult({inputs.get('task_id','')})"
    if name == "ListAgentTasks":   return "ListAgentTasks()"
    if name == "ListAgentTypes":   return "ListAgentTypes()"
    if name == "WritePlan":        return "WritePlan()"
    if name == "Methodology":      return _methodology_desc(inputs)
    if name == "_XmlParseError":      return "Malformed tool call (invalid XML)"
    if name == "_InvalidToolName":    return "Malformed tool call (bad name)"
    if name == "_ToolArgsParseError": return "Malformed tool call (bad args)"
    return f"{name}({list(inputs.values())[:1]})"


def _methodology_desc(inputs: dict) -> str:
    content = (inputs.get("content") or "").strip()
    raw_snippets = inputs.get("snippets")
    snippets = raw_snippets if isinstance(raw_snippets, list) else []
    mode = inputs.get("mode") or "append"
    parts: list[str] = []
    if content:
        short = content.replace("\n", " ")[:60]
        ellipsis = "…" if len(content) > 60 else ""
        parts.append(f'content="{short}{ellipsis}"')
    if raw_snippets and not isinstance(raw_snippets, list):
        parts.append(f"snippets: INVALID (got {type(raw_snippets).__name__}, expected list)")
    elif snippets:
        valid = [s for s in snippets if isinstance(s, dict)]
        rendered = [_snippet_desc(s) for s in valid[:3]]
        tail = f" +{len(valid)-3} more" if len(valid) > 3 else ""
        invalid = len(snippets) - len(valid)
        inv_tag = f" ({invalid} invalid)" if invalid else ""
        parts.append(f"{len(valid)} snippets: {', '.join(rendered)}{tail}{inv_tag}")
    suffix = " [replace]" if mode == "replace" else ""
    body = ", ".join(parts) if parts else "empty"
    return f"Methodology({body}){suffix}"


def _snippet_desc(snippet: dict) -> str:
    fp = snippet.get("file_path", "")
    fname = fp.replace("\\", "/").rsplit("/", 1)[-1] or fp
    ranges = snippet.get("ranges") or []
    rng_parts = [
        f"L{r[0]}-{r[1]}"
        for r in ranges
        if isinstance(r, list) and len(r) == 2
    ]
    rng_str = "+".join(rng_parts) if rng_parts else "?"
    return f"{fname} {rng_str}"
