# [desc] Implements EnterPlanMode and ExitPlanMode tools for read-only planning before code changes. [/desc]
"""Plan mode tools: EnterPlanMode / ExitPlanMode."""
from pathlib import Path


class PlanRejected(Exception):
    """Raised when user rejects a plan during WritePlan with user_validation_required=True."""
    def __init__(self, feedback: str):
        super().__init__(f"Plan rejected: {feedback}")
        self.feedback = feedback


def _persist_plan(content: str, config: dict, plan_path: Path) -> None:
    """Persist plan to _all_plans, IPC, and methodology. Call ONLY after validation."""
    all_plans = config.setdefault("_all_plans", [])
    all_plans.append(content)
    ipc_dir = config.get("_web_agent_dir")
    if ipc_dir:
        ipc_plan = Path(ipc_dir) / "plan.md"
        ipc_plan.write_text("\n\n---\n\n".join(all_plans), encoding="utf-8")
    from ..context_manager.methodology import append_plan_to_methodology
    from ..context_manager.state import resolve_context_state
    append_plan_to_methodology(resolve_context_state(config), content)


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
    user_validation_required = params.get("user_validation_required", False)
    session_id = config.get("_session_id", "default")
    plans_dir = Path.cwd() / ".nano_claude" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plans_dir / f"{session_id}.md"
    plan_path.write_text(content, encoding="utf-8")
    config["_plan_content"] = content
    config.setdefault("_plan_file", str(plan_path))

    # Auto-validate plan (skip if user will validate manually)
    if not user_validation_required:
        from .plan_auto_validator import validate_plan_auto
        approved, feedback = validate_plan_auto(content, config)
        if not approved:
            raise PlanRejected(feedback=f"[Auto-validator] {feedback}")

    if user_validation_required:
        from .interaction import is_web_ipc_active
        if is_web_ipc_active():
            config["_plan_needs_validation"] = True
            ipc_dir = config.get("_web_agent_dir")
            if ipc_dir:
                from bouzecode.web import ipc as _ipc
                _ipc.write_state(
                    _ipc.from_dir(ipc_dir),
                    "awaiting_plan_validation",
                    question="Valides-tu ce plan ?",
                    options=[
                        {"label": "Oui, \u00e7a part", "description": "Approuver et ex\u00e9cuter"},
                        {"label": "Non, \u00e7a ne me va pas", "description": "Rejeter et donner du feedback"},
                    ],
                    allow_freetext=True,
                )
            # Persist plan AFTER auto-validation passes (IPC path)
            _persist_plan(content, config, plan_path)
            return f"Plan saved to {plan_path}\n\n\u23f3 Awaiting user validation..."
        from .interaction import _ask_user_question
        answer = _ask_user_question(
            "Valides-tu ce plan ?",
            [
                {"label": "Oui, \u00e7a part", "description": "Approuver et ex\u00e9cuter"},
                {"label": "Non, \u00e7a ne me va pas", "description": "Rejeter et donner du feedback"},
            ],
            allow_freetext=True,
            config=config,
        )
        from .plan_validation import is_plan_approved
        if not is_plan_approved(answer):
            raise PlanRejected(feedback=answer)

    # Persist plan ONLY after all validation passes
    _persist_plan(content, config, plan_path)
    if user_validation_required:
        return f"Plan saved to {plan_path}\n\n\u2705 Plan validated by user."
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
            "Use this to capture your Phase 2 plan in a parsable, reviewable format. "
            "If user_validation_required is true, the user is asked to approve before "
            "subsequent tools execute. On rejection, all tools after WritePlan are cancelled."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The complete implementation plan in Markdown format.",
                },
                "user_validation_required": {
                    "type": "boolean",
                    "description": (
                        "If true, pause and ask the user to validate the plan before "
                        "executing subsequent tools. Default false."
                    ),
                    "default": False,
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
