# [desc] Implements /plan command to enter, exit, display, and manage plan mode for sessions. [/desc]
"""/plan command — enter/exit plan mode."""
from __future__ import annotations

from pathlib import Path

try:
    from ui.ansi import clr, ok, warn, err, info
except ImportError:
    import sys
    C = {"cyan": "\033[36m", "green": "\033[32m", "yellow": "\033[33m",
         "red": "\033[31m", "bold": "\033[1m", "dim": "\033[2m", "reset": "\033[0m"}
    def clr(text, *keys): return "".join(C[k] for k in keys) + str(text) + C["reset"]
    def info(msg):  print(clr(msg, "cyan"))
    def ok(msg):    print(clr(msg, "green"))
    def warn(msg):  print(clr(f"Warning: {msg}", "yellow"))
    def err(msg):   print(clr(f"Error: {msg}", "red"), file=sys.stderr)


def cmd_plan(args: str, state, config) -> bool:
    """Enter/exit plan mode or show current plan.

    /plan <description>  -- enter plan mode and start planning
    /plan                -- show current plan file contents
    /plan done           -- exit plan mode, restore permissions
    /plan status         -- show plan mode status
    """
    arg = args.strip()
    plan_file = config.get("_plan_file", "")
    in_plan_mode = config.get("permission_mode") == "plan"

    if arg == "done":
        if not in_plan_mode:
            err("Not in plan mode.")
            return True
        prev = config.pop("_prev_permission_mode", "auto")
        config["permission_mode"] = prev
        info(f"Exited plan mode. Permission mode restored to: {prev}")
        if plan_file:
            info(f"Plan saved at: {plan_file}")
            info("You can now ask Claude to implement the plan.")
        return True

    if arg == "status":
        if in_plan_mode:
            info("Plan mode: ACTIVE")
            info(f"Plan file: {plan_file}")
            info("Only the plan file is writable. Use /plan done to exit.")
        else:
            info("Plan mode: inactive")
        return True

    if not arg:
        if not plan_file:
            info("Not in plan mode. Use /plan <description> to start planning.")
            return True
        p = Path(plan_file)
        if p.exists() and p.stat().st_size > 0:
            info(f"Plan file: {plan_file}")
            print(p.read_text(encoding="utf-8"))
        else:
            info(f"Plan file is empty: {plan_file}")
        return True

    if in_plan_mode:
        err("Already in plan mode. Use /plan done to exit first.")
        return True

    session_id = config.get("_session_id", "default")
    plans_dir = Path.cwd() / ".nano_claude" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plans_dir / f"{session_id}.md"
    plan_path.write_text(f"# Plan: {arg}\n\n", encoding="utf-8")

    config["_prev_permission_mode"] = config.get("permission_mode", "auto")
    config["permission_mode"] = "plan"
    config["_plan_file"] = str(plan_path)

    info("Plan mode activated (read-only except plan file).")
    info(f"Plan file: {plan_path}")
    info("Use /plan done to exit and start implementation.")
    print()

    return ("__plan__", arg)
