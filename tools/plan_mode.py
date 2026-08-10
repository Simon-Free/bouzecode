# [desc] Implements EnterPlanMode and ExitPlanMode tools for read-only planning before code changes. [/desc]
"""Plan mode tools: EnterPlanMode / ExitPlanMode."""
from pathlib import Path


def _enter_plan_mode(params: dict, config: dict) -> str:
    if config.get("permission_mode") == "plan":
        return "Already in plan mode. Write your plan to the plan file, then call ExitPlanMode."

    session_id = config.get("_session_id", "default")
    plans_dir = Path.cwd() / ".nano_claude" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plans_dir / f"{session_id}.md"

    task_desc = params.get("task_description", "")
    if not plan_path.exists() or plan_path.stat().st_size == 0:
        header = f"# Plan: {task_desc}\n\n" if task_desc else "# Plan\n\n"
        plan_path.write_text(header, encoding="utf-8")

    config["_prev_permission_mode"] = config.get("permission_mode", "auto")
    config["permission_mode"] = "plan"
    config["_plan_file"] = str(plan_path)

    return (
        f"Plan mode activated. You are now in read-only mode.\n"
        f"Plan file: {plan_path}\n\n"
        f"Instructions:\n"
        f"1. Analyze the codebase using Read, Glob, Grep, WebSearch\n"
        f"2. Write your detailed implementation plan to the plan file using Write or Edit\n"
        f"3. When the plan is ready, call ExitPlanMode to request user approval\n"
        f"4. Do NOT attempt to write to any other files \u2014 they will be blocked"
    )


def _write_plan(params: dict, config: dict) -> str:
    content = params.get("content", "")
    if not content.strip():
        return "Error: plan content is empty."
    session_id = config.get("_session_id", "default")
    plans_dir = Path.cwd() / ".nano_claude" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plans_dir / f"{session_id}.md"
    plan_path.write_text(content, encoding="utf-8")
    config["_plan_content"] = content
    config.setdefault("_plan_file", str(plan_path))
    # Accumulate all plans for multi-plan display
    all_plans = config.setdefault("_all_plans", [])
    all_plans.append(content)
    # Also write into IPC dir for live display in BouzequI
    ipc_dir = config.get("_web_agent_dir")
    if ipc_dir:
        ipc_plan = Path(ipc_dir) / "plan.md"
        ipc_plan.write_text("\n\n---\n\n".join(all_plans), encoding="utf-8")
    return f"Plan saved to {plan_path}"


def _exit_plan_mode(params: dict, config: dict) -> str:
    if config.get("permission_mode") != "plan":
        return "Not in plan mode. Use EnterPlanMode first."

    plan_file = config.get("_plan_file", "")
    plan_content = ""
    if plan_file:
        p = Path(plan_file)
        if p.exists():
            plan_content = p.read_text(encoding="utf-8").strip()

    if not plan_content or plan_content == "# Plan":
        return "Plan file is empty. Write your plan to the plan file before calling ExitPlanMode."

    prev = config.pop("_prev_permission_mode", "auto")
    config["permission_mode"] = prev

    return (
        f"Plan mode exited. Permission mode restored to: {prev}\n"
        f"Plan file: {plan_file}\n\n"
        f"The plan is ready for the user to review. "
        f"Wait for the user to approve before starting implementation.\n\n"
        f"--- Plan Content ---\n{plan_content}"
    )


_PLAN_MODE_SCHEMAS = [
    {
        "name": "EnterPlanMode",
        "description": (
            "Enter plan mode to analyze the codebase and create an implementation plan "
            "before writing code. Use this for complex, multi-file tasks. "
            "In plan mode, only the plan file is writable; all other writes are blocked."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "Brief description of the task to plan for",
                },
            },
            "required": [],
        },
    },
    {
        "name": "WritePlan",
        "description": (
            "Write the implementation plan as a structured Markdown document. "
            "The plan is saved to a file and displayed in a dedicated Plan tab in the UI. "
            "Use this to capture your Phase 2 plan in a parsable, reviewable format."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The complete implementation plan in Markdown format.",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "ExitPlanMode",
        "description": (
            "Exit plan mode and present the plan for user approval. "
            "Call this after writing your implementation plan to the plan file. "
            "The user must approve the plan before you begin implementation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]
