# [desc] Auto-validates implementation plans via LLM, rejecting those missing proper E2E tests or bug repro steps. [/desc]
"""Auto-validate plans before presenting to user.

Calls the LLM with strict test criteria. Default posture: REJECT.
The LLM must find a compelling reason to APPROVE.

Architecture: sends the EXACT same context as the planner (system + messages),
appends the plan as assistant message, then adds validation instructions as the
final user message. This ensures the validator sees the full conversation context.
"""
import re
from ..agent import providers

VALIDATOR_INSTRUCTIONS_SEPARATOR = "=" * 60

VALIDATOR_INSTRUCTIONS = """\
You are a RUTHLESS plan validator. Your default answer is REJECTED.

You must find a REAL, COMPELLING reason to approve a plan. Mediocre plans,
vague plans, plans without proper tests — ALL get rejected.

RULES — a plan MUST satisfy ALL of these to be approved:

1. **Bug fix** → The plan MUST explicitly state writing a FAILING test FIRST
   that reproduces the bug. The test must fail before the fix and pass after.
   No test-first approach = REJECTED.

2. **Feature** → Tests MUST be at the user-facing level:
   - CLI → test the real command (subprocess or CliRunner)
   - HTTP API → test real endpoints (test client)
   - Python library → test the public function/class as the user would import it
   - Frontend → test the rendered output or use Playwright
   - Generated file → verify file content, not internal calls
   Tests must NOT rely on unittest.mock.patch or internal implementation details.
   No user-facing tests = REJECTED.

3. **No manual validation** → The plan must NOT include steps like "manually verify",
   "check visually", "ask the user to confirm". Everything must be automatable.
   Any manual step = REJECTED.

4. **Tests are PRECISE** → The plan must describe EXACTLY what is tested,
   with concrete assertions. Vague statements like "add appropriate tests"
   or "write tests for the feature" = REJECTED.

5. **Plan is complete** → The plan must have: problem statement, solution,
   and test plan. Missing any section = REJECTED.

RESPONSE FORMAT (strict XML — no deviation):

If approved:
<approve>true</approve>

If rejected:
<approve>false</approve>
<feedback>Your detailed reasoning here.</feedback>

IMPORTANT:
- Use EXACTLY "true" or "false" (lowercase) inside the <approve> tag.
- Do NOT include anything before <approve>. No preamble, no thinking, no markdown.
- If rejecting, you MUST include <feedback> explaining which rules are violated.
"""


def validate_plan_auto(plan_content: str, config: dict) -> tuple[bool, str]:
    """Validate a plan automatically via LLM.

    Sends the exact same context as the planner (system + messages from
    last_api_payload), appends the plan as assistant message, then adds
    validation instructions as the final user message.

    Returns (approved: bool, feedback: str).
    If approved, feedback is empty. If rejected, feedback explains why.
    """
    override = config.get("_plan_auto_validate_result")
    if override is not None:
        return override

    state = config.get("_state")
    system_prompt = config.get("_system_prompt", "")

    # Build messages: use the exact planner context if available
    if state and hasattr(state, "last_api_payload") and state.last_api_payload:
        messages = list(state.last_api_payload)
    else:
        # Fallback: build minimal context from methodology
        from ..context_manager.state import resolve_context_state
        gc_state = resolve_context_state(config)
        methodology = ""
        if gc_state and hasattr(gc_state, "notes"):
            methodology = gc_state.notes.get("methodology", "")
        messages = [{"role": "user", "content": f"Context:\n{methodology[:8000]}"}]

    # Append the plan as the assistant's response
    messages.append({"role": "assistant", "content": plan_content})

    # Append validation instructions as final user message
    validation_msg = (
        f"{VALIDATOR_INSTRUCTIONS_SEPARATOR}\n"
        f"INSTRUCTIONS FOR VALIDATION OF THE PRECEDING PLAN\n"
        f"{VALIDATOR_INSTRUCTIONS_SEPARATOR}\n\n"
        f"{VALIDATOR_INSTRUCTIONS}"
    )
    messages.append({"role": "user", "content": validation_msg})

    response_text = ""
    for event in providers.stream(
        model=config.get("_validator_model", config.get("model", "sonnet")),
        system=system_prompt,
        messages=messages,
        tool_schemas=[],
        config=config,
    ):
        if isinstance(event, providers.TextChunk):
            response_text += event.text

    return _parse_verdict(response_text)


def _parse_verdict(response_text: str) -> tuple[bool, str]:
    """Parse XML verdict from validator response.

    Supports two formats:
    - New: <approve>true/false</approve> + <feedback>...</feedback>
    - Legacy: <decision>approved/rejected</decision> + <justification>...</justification>
    Returns (approved, feedback). Default is REJECTED if no valid XML found.
    """
    response_text = response_text.strip()

    # Strip <thinking>...</thinking> blocks (LLM may add them despite instructions)
    response_text = re.sub(r'<thinking>.*?</thinking>', '', response_text, flags=re.DOTALL).strip()

    # Try new format first: <approve>true/false</approve>
    approve_match = re.search(
        r'<approve>\s*(true|false)\s*</approve>',
        response_text,
        re.IGNORECASE,
    )
    if approve_match:
        approved = approve_match.group(1).lower() == "true"
        if approved:
            return True, ""
        feedback_match = re.search(
            r'<feedback>(.*?)</feedback>',
            response_text,
            re.DOTALL,
        )
        if feedback_match:
            return False, feedback_match.group(1).strip()[:500]
        return False, "Plan rejected by auto-validator (no feedback provided)."

    # Fallback: legacy format <decision>approved/rejected</decision>
    decision_match = re.search(
        r'<decision>\s*(approved|rejected)\s*</decision>',
        response_text,
        re.IGNORECASE,
    )
    if decision_match:
        decision = decision_match.group(1).lower()
        if decision == "approved":
            return True, ""
        justification_match = re.search(
            r'<justification>(.*?)</justification>',
            response_text,
            re.DOTALL,
        )
        if justification_match:
            return False, justification_match.group(1).strip()[:500]
        return False, "Plan rejected by auto-validator (no justification provided)."

    # No valid tag found -> REJECT by default
    excerpt = response_text[:200].replace('\n', ' ')
    return False, f"Plan rejected: validator response did not contain a valid <approve> or <decision> tag. Response excerpt: {excerpt}"
