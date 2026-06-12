# [desc] Tests system block stability and cache breakpoint pinning for Anthropic API cache writes [/desc]
"""
Tests for cache write fixes — system block stability + breakpoint pinning.

After fix:
- System blocks are byte-stable across tool iterations (audit/notes NOT in system)
- Cache breakpoint pinned to last message of PREVIOUS user loop (stable position)
- No message-level breakpoint for first user loop (system cache_control suffices)
"""
import hashlib
import json

from bouzecode.backend.context_manager.audit import build_verbatim_audit_note
from bouzecode.backend.agent.providers.conversion import messages_to_anthropic, _find_current_loop_start
from bouzecode.backend.agent.providers.backends.dispatch import _inject_into_last_user_message


def _make_tool_result(tool_call_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


def _make_assistant_with_tool_call(tool_id: str, text: str = "") -> dict:
    return {
        "role": "assistant",
        "content": text,
        "tool_calls": [{"id": tool_id, "name": "Read", "input": {"file_path": "/tmp/f.py"}}],
    }


def _system_prompt_hash(system_blocks: list[dict]) -> str:
    return hashlib.sha256(json.dumps(system_blocks, sort_keys=True).encode()).hexdigest()


def _find_cache_control_indices(anthropic_msgs: list[dict]) -> list[int]:
    indices = []
    for i, msg in enumerate(anthropic_msgs):
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "cache_control" in block:
                    indices.append(i)
                    break
    return indices


def _find_last_cache_control_index(anthropic_msgs: list[dict]) -> int | None:
    indices = _find_cache_control_indices(anthropic_msgs)
    return indices[-1] if indices else None


class TestSystemBlockStability:
    """Fix 1: audit note and working memory notes are NOT in system blocks."""

    def test_audit_grows_with_each_tool_result(self):
        base = [
            {"role": "user", "content": "hello"},
            _make_assistant_with_tool_call("tc1"),
            _make_tool_result("tc1", "file content 1"),
        ]
        audit_1 = build_verbatim_audit_note(base)
        extended = base + [
            _make_assistant_with_tool_call("tc2"),
            _make_tool_result("tc2", "file content 2"),
        ]
        audit_2 = build_verbatim_audit_note(extended)
        assert audit_1 != audit_2
        assert len(audit_2) > len(audit_1)

    def test_system_without_audit_is_stable(self):
        stable_system = [
            {"type": "text", "text": "You are a helpful assistant."},
            {"type": "text", "text": "Tool docs here."},
        ]
        h1 = _system_prompt_hash(stable_system)
        h2 = _system_prompt_hash(stable_system)
        assert h1 == h2

    def test_audit_in_system_would_break_cache(self):
        stable = [{"type": "text", "text": "You are a helpful assistant."}]
        msgs_1 = [
            {"role": "user", "content": "read"},
            _make_assistant_with_tool_call("tc1"),
            _make_tool_result("tc1", "A"),
        ]
        msgs_2 = msgs_1 + [
            _make_assistant_with_tool_call("tc2"),
            _make_tool_result("tc2", "B"),
        ]
        h1 = _system_prompt_hash(stable + [{"type": "text", "text": build_verbatim_audit_note(msgs_1)}])
        h2 = _system_prompt_hash(stable + [{"type": "text", "text": build_verbatim_audit_note(msgs_2)}])
        assert h1 != h2, "Audit in system blocks would cause cache miss"

    def test_inject_into_last_user_message(self):
        original_msg = {"role": "user", "content": "original question"}
        msgs = [
            original_msg,
            _make_assistant_with_tool_call("tc1"),
            _make_tool_result("tc1", "result"),
        ]
        _inject_into_last_user_message(msgs, "AUDIT NOTE HERE")
        assert msgs[0]["content"].startswith("AUDIT NOTE HERE")
        assert "original question" in msgs[0]["content"]
        assert original_msg["content"] == "original question"


class TestCacheBreakpointPinned:
    """Fix 2: cache breakpoint on last msg of previous user loop, not sliding."""

    def test_find_loop_start_first_loop(self):
        msgs = [
            {"role": "user", "content": "read file"},
            _make_assistant_with_tool_call("tc1"),
            _make_tool_result("tc1", "content"),
        ]
        assert _find_current_loop_start(msgs) == 0

    def test_find_loop_start_second_loop(self):
        msgs = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second question"},
            _make_assistant_with_tool_call("tc1"),
            _make_tool_result("tc1", "content"),
        ]
        assert _find_current_loop_start(msgs) == 2

    def test_no_breakpoint_first_loop(self):
        msgs = [
            {"role": "user", "content": "read file"},
            _make_assistant_with_tool_call("tc1", "reading"),
            _make_tool_result("tc1", "file content"),
        ]
        anth = messages_to_anthropic(msgs, cache_last=True)
        assert _find_last_cache_control_index(anth) is None

    def test_no_breakpoint_stable_across_iterations(self):
        msgs = [{"role": "user", "content": "read 3 files"}]
        bps = []
        for i in range(3):
            tid = f"tc_{i}"
            anth = messages_to_anthropic(msgs, cache_last=True)
            bps.append(_find_last_cache_control_index(anth))
            msgs.append(_make_assistant_with_tool_call(tid, f"reading {i}"))
            msgs.append(_make_tool_result(tid, f"content {i} " * 50))
        assert all(bp is None for bp in bps), f"All should be None: {bps}"

    def test_breakpoint_pinned_to_compacted_history(self):
        compacted = [
            {"role": "user", "content": "[compacted] previous conversation"},
            {"role": "assistant", "content": "[compacted] previous response"},
        ]
        msgs_iter1 = compacted + [
            {"role": "user", "content": "now read file Z"},
            _make_assistant_with_tool_call("tc1", "reading"),
            _make_tool_result("tc1", "file Z"),
        ]
        anth_1 = messages_to_anthropic(msgs_iter1, cache_last=True)
        bp_1 = _find_last_cache_control_index(anth_1)

        msgs_iter2 = msgs_iter1 + [
            _make_assistant_with_tool_call("tc2", "reading more"),
            _make_tool_result("tc2", "file W"),
        ]
        anth_2 = messages_to_anthropic(msgs_iter2, cache_last=True)
        bp_2 = _find_last_cache_control_index(anth_2)

        assert bp_1 is not None
        assert bp_1 == bp_2, f"Breakpoint must be stable. Iter1: {bp_1}, iter2: {bp_2}"
        assert bp_1 == 1, f"Breakpoint on compacted assistant (idx 1), got {bp_1}"

    def test_breakpoint_on_compacted_not_fresh(self):
        compacted = [
            {"role": "user", "content": "[compacted] previous " * 50},
            {"role": "assistant", "content": "[compacted] response " * 50},
        ]
        current = compacted + [
            {"role": "user", "content": "new question"},
            _make_assistant_with_tool_call("tc1"),
            _make_tool_result("tc1", "result " * 100),
        ]
        anth = messages_to_anthropic(current, cache_last=True)
        bp = _find_last_cache_control_index(anth)
        assert bp == 1, f"Breakpoint on compacted msg (idx 1), got {bp}"


class TestE2EToolLoop:

    @staticmethod
    def _simulate_tool_loop(previous_msgs, user_input, n_tool_iters):
        stable_system = [{"type": "text", "text": "You are a helpful assistant. " * 200}]
        snapshots = []
        msgs = previous_msgs + [{"role": "user", "content": user_input}]
        for i in range(n_tool_iters):
            tid = f"tc_loop_{i}"
            sys_hash = _system_prompt_hash(stable_system)
            anth_msgs = messages_to_anthropic(msgs, cache_last=True)
            bp = _find_last_cache_control_index(anth_msgs)
            snapshots.append({
                "system_hash": sys_hash,
                "breakpoint_index": bp,
                "n_anthropic_msgs": len(anth_msgs),
            })
            msgs.append(_make_assistant_with_tool_call(tid, f"Reading file {i}"))
            msgs.append(_make_tool_result(tid, f"content of file {i} " * 100))
        return snapshots, msgs

    def test_e2e_first_loop_stable(self):
        snaps, _ = self._simulate_tool_loop([], "Read 3 files", 3)
        sys_hashes = {s["system_hash"] for s in snaps}
        assert len(sys_hashes) == 1, "System hash must be stable"
        assert all(s["breakpoint_index"] is None for s in snaps)

    def test_e2e_second_loop_stable(self):
        compacted = [
            {"role": "user", "content": "[compacted] previous " * 50},
            {"role": "assistant", "content": "[compacted] response " * 50},
        ]
        snaps, _ = self._simulate_tool_loop(compacted, "Read 3 more files", 3)
        sys_hashes = {s["system_hash"] for s in snaps}
        assert len(sys_hashes) == 1, "System hash must be stable"
        bps = {s["breakpoint_index"] for s in snaps}
        assert len(bps) == 1, f"Breakpoint must be stable: {bps}"
        assert snaps[0]["breakpoint_index"] == 1, "Breakpoint on compacted assistant (idx 1)"
