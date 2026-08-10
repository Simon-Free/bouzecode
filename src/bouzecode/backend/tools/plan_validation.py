# [desc] Validates user plan approval: only the input "1" counts as approved. [/desc]
"""Plan validation helper — ultra-simple logic.

Only "1" approves the plan. Everything else is a rejection with the text as feedback.
"""


def is_plan_approved(response: str) -> bool:
    return response.strip() == "1"
