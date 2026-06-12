# [desc] Tests that Skill tool results require Snippet coverage like Read results in enforcement hooks
# <tool_use name="FinalAnswer" id="fa1"><param name="answer">Tests that Skill tool results require Snippet coverage like Read results in enforcement hooks</param></tool_use> [/desc]
"""Tests that Skill results are tracked by enforcement like Read results."""

from bouzecode.backend.tools.enforcement_hooks import get_unsnippeted_reads, check_enforcement


SKILL_FILE_PATH = "/home/user/.bouzecode/skills/commit/skill.md"

# Content must be >= SNIPPET_MIN_LINES (50) to trigger enforcement
_BIG_SKILL_CONTENT = (
    f"[Skill: commit | file: {SKILL_FILE_PATH}]\n\n"
    + "\n".join(f"# Skill line {i}" for i in range(1, 55))
)


def _make_messages_with_skill(*, snippet_after=False, discard_after=False):
    """Build a message history where assistant called Skill, got result."""
    assistant_msg = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "tc_skill_1",
                "name": "Skill",
                "input": {"name": "commit"},
            }
        ],
    }
    tool_result_msg = {
        "role": "tool",
        "tool_call_id": "tc_skill_1",
        "name": "Skill",
        "content": _BIG_SKILL_CONTENT,
    }
    messages = [assistant_msg, tool_result_msg]

    if snippet_after:
        messages.append({
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "tc_snippet_1",
                    "name": "Snippet",
                    "input": {"file_path": SKILL_FILE_PATH, "ranges": [[1, 10]], "label": "commit skill"},
                }
            ],
        })
    elif discard_after:
        messages.append({
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "tc_snippet_1",
                    "name": "Snippet",
                    "input": {"file_path": SKILL_FILE_PATH, "discard": True},
                }
            ],
        })

    return messages


def test_skill_without_snippet_triggers_enforcement():
    """Skill result without Snippet should be flagged as unsnippeted."""
    messages = _make_messages_with_skill()
    unsnippeted = get_unsnippeted_reads(messages)
    assert len(unsnippeted) == 1
    assert unsnippeted[0]["file_path"] == SKILL_FILE_PATH
    assert unsnippeted[0]["line_count"] > 0

    # With empty tool_calls (no Methodology either) → "BOTH" message
    warning = check_enforcement([], unsnippeted_reads=unsnippeted)
    assert warning is not None
    assert "Read/Skill" in warning

    # With Methodology present → snippet-only message
    methodology_tc = [{"name": "Methodology", "input": {"content": "test"}}]
    warning2 = check_enforcement(methodology_tc, unsnippeted_reads=unsnippeted)
    assert warning2 is not None
    assert "Read/Skill" in warning2


def test_skill_with_snippet_passes():
    """Skill result followed by Snippet with matching path should pass."""
    messages = _make_messages_with_skill(snippet_after=True)
    unsnippeted = get_unsnippeted_reads(messages)
    assert len(unsnippeted) == 0


def test_skill_with_discard_passes():
    """Skill result followed by Snippet(discard=true) should pass."""
    messages = _make_messages_with_skill(discard_after=True)
    unsnippeted = get_unsnippeted_reads(messages)
    assert len(unsnippeted) == 0


def test_read_and_skill_mixed_both_must_be_covered():
    """Both Read and Skill results need independent Snippet coverage."""
    read_path = "/home/user/project/main.py"
    # Both contents must be >= SNIPPET_MIN_LINES to trigger enforcement
    big_read_content = "\n".join(f"{i}\tline {i}" for i in range(1, 55))
    big_skill_content = (
        f"[Skill: commit | file: {SKILL_FILE_PATH}]\n\n"
        + "\n".join(f"# skill line {i}" for i in range(1, 55))
    )
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "tc_read_1", "name": "Read", "input": {"file_path": read_path}},
                {"id": "tc_skill_1", "name": "Skill", "input": {"name": "commit"}},
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "tc_read_1",
            "name": "Read",
            "content": big_read_content,
        },
        {
            "role": "tool",
            "tool_call_id": "tc_skill_1",
            "name": "Skill",
            "content": big_skill_content,
        },
    ]
    unsnippeted = get_unsnippeted_reads(messages)
    assert len(unsnippeted) == 2
    paths = {r["file_path"] for r in unsnippeted}
    assert read_path in paths
    assert SKILL_FILE_PATH in paths

    # Cover only Read — Skill should still be flagged
    messages_with_partial_snippet = messages + [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "tc_sn_1",
                    "name": "Snippet",
                    "input": {"file_path": read_path, "ranges": [[1, 2]], "label": "main"},
                }
            ],
        }
    ]
    unsnippeted2 = get_unsnippeted_reads(messages_with_partial_snippet)
    assert len(unsnippeted2) == 1
    assert unsnippeted2[0]["file_path"] == SKILL_FILE_PATH


def test_skill_without_file_in_result_skips_enforcement():
    """If Skill result doesn't have parseable file path, skip enforcement for it."""
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "tc_skill_1", "name": "Skill", "input": {"name": "commit"}},
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "tc_skill_1",
            "name": "Skill",
            "content": "Error: skill 'commit' not found. Available: review, test",
        },
    ]
    unsnippeted = get_unsnippeted_reads(messages)
    assert len(unsnippeted) == 0
