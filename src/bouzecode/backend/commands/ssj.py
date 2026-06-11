# [desc] Interactive power menu providing SSJ Developer Mode workflow commands for project tasks. [/desc]
"""SSJ Developer Mode — Interactive power menu for project workflows."""

import time
from pathlib import Path

try:
    from bouzecode.ui.ansi import clr, ok, err, info, warn
except ImportError:
    import sys
    C = {"cyan": "\033[36m", "green": "\033[32m", "yellow": "\033[33m",
         "red": "\033[31m", "bold": "\033[1m", "dim": "\033[2m", "reset": "\033[0m"}
    def clr(text, *keys): return "".join(C[k] for k in keys) + str(text) + C["reset"]
    def info(msg):  print(clr(msg, "cyan"))
    def ok(msg):    print(clr(msg, "green"))
    def warn(msg):  print(clr(f"Warning: {msg}", "yellow"))
    def err(msg):   print(clr(f"Error: {msg}", "red"), file=sys.stderr)

from bouzecode.backend.tools.interaction import ask_input_interactive

_SSJ_MENU = (
    clr("\n╭─ SSJ Developer Mode ", "dim") + clr("⚡", "yellow") + clr(" ─────────────────────────", "dim")
    + "\n│"
    + "\n│  " + clr(" 1.", "bold") + " 💡  Brainstorm — Multi-persona AI debate"
    + "\n│  " + clr(" 2.", "bold") + " 📋  Show TODO — View todo_list.txt"
    + "\n│  " + clr(" 3.", "bold") + " 👷  Worker — Auto-implement pending tasks"
    + "\n│  " + clr(" 4.", "bold") + " 🧠  Debate — Expert debate on a file"
    + "\n│  " + clr(" 5.", "bold") + " ✨  Propose — AI improvement for a file"
    + "\n│  " + clr(" 6.", "bold") + " 🔎  Review — Quick file analysis"
    + "\n│  " + clr(" 7.", "bold") + " 📘  Readme — Auto-generate README.md"
    + "\n│  " + clr(" 8.", "bold") + " 💬  Commit — AI-suggested commit message"
    + "\n│  " + clr(" 9.", "bold") + " 🧪  Scan — Analyze git diff"
    + "\n│  " + clr("10.", "bold") + " 📝  Promote — Idea to tasks"
    + "\n│  " + clr("11.", "bold") + " 🎬  Video — AI video content factory"
    + "\n│  " + clr(" 0.", "bold") + " 🚪  Exit SSJ Mode  (or type q)"
    + "\n│"
    + "\n" + clr("╰──────────────────────────────────────────────", "dim")
)


def _pick_file(config, prompt_text="  Select file #: ", exts=None):
    """Show numbered file list and let user pick one."""
    files = sorted([
        f for f in Path(".").iterdir()
        if f.is_file() and not f.name.startswith(".")
        and (exts is None or f.suffix in exts)
    ])
    if not files:
        err("No matching files found in current directory.")
        return None
    menu_text = clr(f"\n  📂 Files in {Path.cwd().name}/", "cyan")
    for i, f in enumerate(files, 1):
        menu_text += ("\n" + f"  {i:3d}. {f.name}")
    sel = ask_input_interactive(clr(prompt_text, "cyan"), config, menu_text).strip()
    if sel.isdigit() and 1 <= int(sel) <= len(files):
        return str(files[int(sel) - 1])
    elif sel:
        return sel
    err("Invalid selection.")
    return None


def _handle_worker_choice(config):
    """Choice 3: Worker — collect path/task/worker args and return sentinel."""
    _default_todo = Path("brainstorm_outputs") / "todo_list.txt"
    if _default_todo.exists():
        _lines = _default_todo.read_text(encoding="utf-8", errors="replace").splitlines()
        _pend = sum(1 for l in _lines if l.strip().startswith("- [ ]"))
        _done = sum(1 for l in _lines if l.strip().startswith("- [x]"))
        print(clr(f"\n  📋 Default todo: brainstorm_outputs/todo_list.txt  "
                  f"({_done} done / {_pend} pending)", "cyan"))
    else:
        print(clr("\n  ℹ  No brainstorm_outputs/todo_list.txt yet. "
                  "You can specify a path or generate one from a brainstorm file.", "dim"))
    print(clr("  ──────────────────────────────────────────────────────", "dim"))
    print(clr("  Note: todo file must contain tasks in '- [ ] task' format.", "dim"))
    todo_input = ask_input_interactive(clr("  Path to todo file (Enter for default): ", "cyan"), config).strip()

    _original_md = None
    if todo_input.endswith(".md") and "brainstorm_" in todo_input:
        warn("That looks like a brainstorm output file, not a todo list.")
        _suggested = str(Path(todo_input).parent / "todo_list.txt")
        print(clr(f"  Suggested todo path: {_suggested}", "yellow"))
        _fix = ask_input_interactive(clr("  Use that path instead? [Y/n]: ", "cyan"), config).strip().lower()
        if _fix in ("", "y"):
            _original_md = todo_input
            todo_input = _suggested

    task_num = ask_input_interactive(clr("  Task # (Enter for all, or e.g. 1,4,6): ", "cyan"), config).strip()
    workers = ask_input_interactive(clr("  Max tasks this session (Enter for all): ", "cyan"), config).strip()

    _resolved = Path(todo_input) if todo_input else _default_todo
    if not _resolved.exists():
        if _original_md and Path(_original_md).exists():
            print(clr(f"\n  ℹ  {_resolved} not found.", "yellow"))
            _gen = ask_input_interactive(
                clr(f"  Generate todo_list.txt from {Path(_original_md).name} first, then run Worker? [Y/n]: ", "cyan"),
                config).strip().lower()
            if _gen in ("", "y"):
                return ("__ssj_promote_worker__", _original_md, str(_resolved), task_num, workers)
    arg_parts = []
    if todo_input:
        arg_parts.append(f"--path {todo_input}")
    if task_num:
        arg_parts.append(f"--tasks {task_num}")
    if workers and workers.isdigit() and int(workers) >= 1:
        arg_parts.append(f"--workers {workers}")
    return ("__ssj_cmd__", "worker", " ".join(arg_parts))

def cmd_ssj(args: str, state, config) -> bool:
    """SSJ Developer Mode — Interactive power menu for project workflows.

    Usage: /ssj
    """
    print(_SSJ_MENU)

    while True:
        try:
            choice = ask_input_interactive(clr("\n  ⚡ SSJ » ", "yellow", "bold"), config, _SSJ_MENU).strip()
        except (KeyboardInterrupt, EOFError):
            break

        if choice.startswith("/"):
            return ("__ssj_passthrough__", choice)
        if choice == "0" or choice.lower() in ("exit", "q"):
            ok("Exiting SSJ Mode.")
            break
        elif choice == "1":
            topic = ask_input_interactive(clr("  Topic (Enter for general): ", "cyan"), config).strip()
            return ("__ssj_cmd__", "brainstorm", topic)
        elif choice == "2":
            todo_path = Path("brainstorm_outputs") / "todo_list.txt"
            if todo_path.exists():
                content = todo_path.read_text(encoding="utf-8", errors="replace")
                lines = content.splitlines()
                task_lines = [(i, l) for i, l in enumerate(lines) if l.strip().startswith("- [")]
                pending_lines = [(i, l) for i, l in task_lines if l.strip().startswith("- [ ]")]
                done_lines = [(i, l) for i, l in task_lines if l.strip().startswith("- [x]")]
                print(clr(f"\n  📋 TODO List ({len(done_lines)} done / {len(pending_lines)} pending):", "cyan"))
                print(clr("  " + "─" * 46, "dim"))
                for _, ln in done_lines:
                    print(clr(f"       ✓ {ln.strip()[5:].strip()}", "green"))
                for num, (_, ln) in enumerate(pending_lines, 1):
                    print(f"  {num:3d}. ○ {ln.strip()[5:].strip()}")
                print(clr("  " + "─" * 46, "dim"))
                print(clr("  Tip: use Worker (3) with pending task #s e.g. 1,4,6", "dim"))
            else:
                err("No todo_list.txt found. Run Brainstorm (1) first.")
            print(_SSJ_MENU)
            continue
        elif choice == "3":
            return _handle_worker_choice(config)
        elif choice == "4":
            filepath = _pick_file(config, "  File to debate #: ")
            if not filepath:
                continue
            _nagents_raw = ask_input_interactive(clr("  Number of debate agents (Enter for 2): ", "cyan"), config).strip()
            try:
                _nagents = max(2, int(_nagents_raw)) if _nagents_raw else 2
            except ValueError:
                err("Invalid number, using 2.")
                _nagents = 2
            _rounds = max(1, (_nagents * 2 - 1))
            _fp = Path(filepath)
            _debate_out = str(_fp.parent / f"{_fp.stem}_debate_{time.strftime('%H%M%S')}.md")
            info(f"Debate result will be saved to: {_debate_out}")
            return ("__ssj_debate__", filepath, _nagents, _rounds, _debate_out)
        elif choice in ("5", "6", "7"):
            _prompts = {
                "5": ("  File to improve #: ", None,
                      "Read {f} and propose specific, concrete improvements. For each improvement: explain the problem, show the fix, and apply it with Edit if the user approves. Focus on bugs, performance, readability, and security. Be concise."),
                "6": ("  File to review #: ", None,
                      "Read {f} and provide a thorough code review. Rate it 1-10 on: readability, maintainability, performance, security. List specific issues with line numbers. Do NOT modify the file, review only."),
                "7": ("  Generate README for file #: ", {".py", ".js", ".ts", ".go", ".rs"},
                      "Read ONLY the file {f}. Based on that single file, generate a professional README.md. Include: project description, features, installation, usage with examples, and contributing guidelines. Use the Write tool to create README.md. Do NOT read other files unless the user explicitly asks."),
            }
            prompt_text, exts, tpl = _prompts[choice]
            filepath = _pick_file(config, prompt_text, exts=exts)
            if not filepath:
                continue
            return ("__ssj_query__", tpl.format(f=filepath))
        elif choice == "8":
            return ("__ssj_query__", "Run 'git diff --cached' and 'git diff' using Bash, analyze ALL changes, and suggest a concise, descriptive commit message following conventional commits format. Show the suggested message and ask for confirmation before committing.")
        elif choice == "9":
            return ("__ssj_query__", "Run 'git status' and 'git diff' using Bash. Analyze the current state of the repository. Summarize: what files changed, what was added/removed, potential issues in the changes, and suggest next steps.")
        elif choice == "10":
            brainstorm_dir = Path("brainstorm_outputs")
            if not brainstorm_dir.exists() or not list(brainstorm_dir.glob("*.md")):
                err("No brainstorm outputs found. Run Brainstorm (1) first.")
                continue
            latest = sorted(brainstorm_dir.glob("*.md"))[-1]
            return ("__ssj_query__", f"Read the brainstorm file {latest} and extract all actionable ideas. Convert each idea into a task with checkbox format (- [ ] task description). Write them to brainstorm_outputs/todo_list.txt using the Write tool. Prioritize by impact.")
        elif choice == "11":
            return ("__ssj_cmd__", "video", "")
        else:
            err("Invalid option. Pick 0-11.")

    return True
