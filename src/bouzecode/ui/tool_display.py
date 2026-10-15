# [desc] Formats and prints tool invocation start/end status with ANSI colors, diffs, and duration info. [/desc]
from .ansi import C, clr
from .rendering import _neutralize_tool_markup, safe_print

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.rule import Rule
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


def _fmt_value(value) -> str:
    """repr() a param value, truncating long strings to 100 chars with an ellipsis.

    Strings keep their quotes ("foo…"); other types are repr'd then truncated so
    a huge list/dict can't blow up the line either.
    """
    if isinstance(value, str):
        if len(value) > 100:
            return f'"{value[:100]}…"'
        return f'"{value}"'
    rendered = repr(value)
    if len(rendered) > 100:
        return rendered[:100] + "…"
    return rendered


def _format_tool_call(name: str, inputs: dict) -> str:
    """Render a tool call in a black-style multiline form with every param shown:

        Tool1(
            param_1="some_stuff…",
            param_2=42,
        )

    An empty input dict renders as ``Tool1()`` on a single line.
    """
    if not inputs:
        return f"{name}()"
    lines = [f"{name}("]
    for key, value in inputs.items():
        lines.append(f"    {key}={_fmt_value(value)},")
    lines.append(")")
    return _neutralize_tool_markup("\n".join(lines))


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


def _print_final_answer(answer: str) -> None:
    """Render FinalAnswer's `answer` as rich Markdown (like an assistant message)
    instead of the generic '✓ FinalAnswer → N lines' tool-result summary."""
    answer = (answer or "").strip()
    print()
    if _RICH_CONSOLE is not None:
        safe_print(Rule(style="green"))
        safe_print(Markdown(_neutralize_tool_markup(answer)), answer)
    else:
        print(answer)
    print()


_CLOTURE_LIVREE = "Session closing — final answer delivered:\n"
_CLOTURE_REFUSEE = ("CLÔTURE", "Error")


def _print_final_answer_outcome(result: str, answer: str) -> None:
    """Clôture livrée : la réponse en Markdown (le texte livré, avec ses avertissements).
    Clôture refusée par le harnais : UNE ligne grise — session B4 (2026-10-14), le rapport
    complet d'une clôture refusée (enfants encore actifs) s'imprimait dans le fil principal."""
    if result.startswith(_CLOTURE_LIVREE):
        _print_final_answer(result[len(_CLOTURE_LIVREE):])
    elif result.lstrip().startswith(_CLOTURE_REFUSEE):
        motif = result.strip().splitlines()[0][:160]
        print(clr(f"  ⏸ FinalAnswer non livrée — {motif}", "dim"), flush=True)
    else:  # résultat inconnu (rejeu sans résultat) : la réponse telle qu'appelée
        _print_final_answer(answer)


def _print_tool_call_block(name: str, inputs: dict) -> None:
    """Print the black-style call block, glyph-prefixed and indented by 2 spaces."""
    block = _format_tool_call(name, inputs)
    indented = block.replace("\n", "\n     ")
    print(clr(f"  \u2699  {indented}", "dim", "cyan"), flush=True)


def print_tool_start(name: str, inputs: dict, verbose: bool):
    if name == "FinalAnswer":
        return  # rendue à la FIN : une clôture refusée ne s'affiche pas (print_tool_end)
    _print_tool_call_block(name, inputs)
    if name == "WritePlan":
        content = inputs.get("content", "")
        print()
        print(clr("  Plan :", "bold", "cyan"))
        print()
        plain = "\n".join(f"    {line}" for line in content.splitlines())
        if _RICH_CONSOLE is not None:
            safe_print(Panel(Markdown(content), border_style="cyan", padding=(0, 2)), plain)
        else:
            print(plain)
        print()
    if name == "Methodology":
        _print_methodology_delta(inputs.get("content", ""))


def _print_methodology_delta(content: str) -> None:
    """Affiche le delta ajouté à la note ce tour-ci, sous un intitulé, comme le plan
    (la ligne d'appel ne montre que les 100 premiers caractères)."""
    content = (content or "").strip()
    if not content:
        return
    print(clr("  Méthodologie :", "bold", "magenta"))
    plain = "\n".join(f"    {line}" for line in content.splitlines())
    if _RICH_CONSOLE is not None:
        safe_print(Panel(Markdown(_neutralize_tool_markup(content)), border_style="magenta",
                         padding=(0, 2)), plain)
    else:
        print(plain)


def print_tool_end(name: str, result: str, verbose: bool, duration: float = 0.0,
                    tool_id: str = "", inputs: dict | None = None):
    if name == "FinalAnswer":
        _print_final_answer_outcome(result, (inputs or {}).get("answer", ""))
        return
    if name == "WritePlan":
        dur_str = f" [{_fmt_duration(duration)}]" if duration > 0 else ""
        print(clr(f"  \u2713 Plan saved{dur_str}", "dim", "green"), flush=True)
        return
    if name == "Methodology" and not _is_failure(name, result):
        # Le delta a été affiché au démarrage : « → 1 lines (35 chars) » n'apprend rien.
        dur_str = f" [{_fmt_duration(duration)}]" if duration > 0 else ""
        print(clr(f"  ✓ Methodology noted{dur_str}", "dim", "green"), flush=True)
        return
    lines = result.count("\n") + 1
    size = len(result)
    dur_suffix = f" [{_fmt_duration(duration)}]" if duration > 0 else ""
    summary = f"{name} \u2192 {lines} lines ({size} chars){dur_suffix}"
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

