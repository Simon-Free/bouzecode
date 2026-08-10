# [desc] Formats and prints tool invocation start/end status with ANSI colors, diffs, and duration info. [/desc]
# [desc] Formats and prints tool invocation start/end status with ANSI colors, diffs, and duration info. [/desc]
import json
from ui.ansi import C, clr

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    _RICH_CONSOLE = Console()
except ImportError:
    _RICH_CONSOLE = None

_last_diffs: dict[str, str] = {}


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


def print_tool_end(name: str, result: str, verbose: bool, duration: float = 0.0):
    if name == "WritePlan":
        dur_str = f" [{_fmt_duration(duration)}]" if duration > 0 else ""
        print(clr(f"  \u2713 Plan saved{dur_str}", "dim", "green"), flush=True)
        return
    lines = result.count("\n") + 1
    size = len(result)
    dur_suffix = f" [{_fmt_duration(duration)}]" if duration > 0 else ""
    summary = f"\u2192 {lines} lines ({size} chars){dur_suffix}"
    if not result.startswith("Error") and not result.startswith("Denied"):
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
    if name == "Read":   return f"Read({inputs.get('file_path','')})"
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
    return f"{name}({list(inputs.values())[:1]})"
