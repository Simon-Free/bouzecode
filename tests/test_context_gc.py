# [desc] Unit tests for context garbage collection helpers including anchor finding, snippet trimming, and GC state management. [/desc]
from context_gc import GCState, process_gc_call, apply_gc, inject_notes, _find_anchor_line, _apply_snippet


class TestFindAnchorLine:
    def test_finds_exact_line(self):
        lines = ["import os", "import sys", "", "def main():", "    pass"]
        assert _find_anchor_line(lines, "import os") == 0
        assert _find_anchor_line(lines, "def main") == 3

    def test_finds_substring(self):
        lines = ["    def handle_request(self):", "        pass"]
        assert _find_anchor_line(lines, "handle_request") == 0

    def test_returns_none_when_not_found(self):
        lines = ["line1", "line2"]
        assert _find_anchor_line(lines, "nonexistent") is None

    def test_start_from(self):
        lines = ["import os", "import sys", "import os"]
        assert _find_anchor_line(lines, "import os", start_from=1) == 2


class TestApplySnippet:
    def test_keep_after(self):
        content = "header\nimport os\n\ndef main():\n    pass\n    return 1"
        result = _apply_snippet(content, {"id": "r1", "keep_after": "def main"})
        assert "def main():" in result
        assert "    pass" in result
        assert "header" not in result
        assert "trimmed" in result

    def test_keep_before(self):
        content = "import os\nimport sys\n\ndef main():\n    pass"
        result = _apply_snippet(content, {"id": "r1", "keep_before": "def main"})
        assert "import os" in result
        assert "import sys" in result
        assert "pass" not in result
        assert "trimmed" in result

    def test_keep_between(self):
        content = "header\nclass Config:\n    x = 1\n    y = 2\nclass Server:\n    pass\nfooter"
        result = _apply_snippet(content, {"id": "r1", "keep_between": ["class Config:", "class Server:"]})
        assert "class Config:" in result
        assert "x = 1" in result
        assert "class Server:" in result
        assert "header" not in result
        assert "footer" not in result

    def test_anchor_not_found_keep_after(self):
        content = "line1\nline2"
        result = _apply_snippet(content, {"id": "r1", "keep_after": "nonexistent"})
        assert "line1" in result
        assert "warning" in result.lower()

    def test_anchor_not_found_keep_before(self):
        content = "line1\nline2"
        result = _apply_snippet(content, {"id": "r1", "keep_before": "nonexistent"})
        assert "line1" in result
        assert "warning" in result.lower()

    def test_anchor_not_found_keep_between_start(self):
        content = "line1\nline2"
        result = _apply_snippet(content, {"id": "r1", "keep_between": ["no_start", "line2"]})
        assert "warning" in result.lower()

    def test_anchor_not_found_keep_between_end(self):
        content = "line1\nline2"
        result = _apply_snippet(content, {"id": "r1", "keep_between": ["line1", "no_end"]})
        assert "warning" in result.lower()

    def test_empty_content(self):
        assert _apply_snippet("", {"id": "r1", "keep_after": "x"}) == ""

    def test_no_anchor_type_returns_content(self):
        content = "some content"
        assert _apply_snippet(content, {"id": "r1"}) == content

    def test_keep_between_wrong_anchor_count(self):
        result = _apply_snippet("content", {"id": "r1", "keep_between": ["only_one"]})
        assert "warning" in result.lower()


class TestProcessGCCall:
    def test_trash(self):
        gc = GCState()
        config = {"_gc_state": gc}
        result = process_gc_call({"trash": ["r1", "r2"]}, config)
        assert "trashed 2" in result
        assert gc.trashed_ids == {"r1", "r2"}

    def test_snippets(self):
        gc = GCState()
        config = {"_gc_state": gc}
        process_gc_call({"keep_snippets": [{"id": "r1", "keep_after": "def main"}]}, config)
        assert "r1" in gc.snippets

    def test_trash_removes_snippet(self):
        gc = GCState(snippets={"r1": {"id": "r1", "keep_after": "x"}})
        config = {"_gc_state": gc}
        process_gc_call({"trash": ["r1"]}, config)
        assert "r1" in gc.trashed_ids
        assert "r1" not in gc.snippets

    def test_snippet_on_trashed_id_ignored(self):
        gc = GCState(trashed_ids={"r1"})
        config = {"_gc_state": gc}
        process_gc_call({"keep_snippets": [{"id": "r1", "keep_after": "x"}]}, config)
        assert "r1" not in gc.snippets

    def test_notes_save(self):
        gc = GCState()
        config = {"_gc_state": gc}
        result = process_gc_call({"notes": [{"name": "plan", "content": "do stuff"}]}, config)
        assert gc.notes["plan"] == "do stuff"
        assert "1 notes saved" in result

    def test_notes_overwrite(self):
        gc = GCState()
        config = {"_gc_state": gc}
        process_gc_call({"notes": [{"name": "plan", "content": "v1"}]}, config)
        process_gc_call({"notes": [{"name": "plan", "content": "v2"}]}, config)
        assert gc.notes["plan"] == "v2"

    def test_trash_notes(self):
        gc = GCState(notes={"old": "stale"})
        config = {"_gc_state": gc}
        result = process_gc_call({"trash_notes": ["old"]}, config)
        assert "old" not in gc.notes
        assert "1 notes removed" in result

    def test_no_gc_state(self):
        result = process_gc_call({"trash": ["r1"]}, {})
        assert "error" in result.lower()

    def test_empty_call(self):
        gc = GCState()
        config = {"_gc_state": gc}
        result = process_gc_call({}, config)
        assert "GC applied" in result


class TestApplyGC:
    def test_trash_replaces_content(self):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "ok", "tool_calls": [{"id": "r1", "name": "Read", "input": {}}]},
            {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": "big file content here"},
        ]
        gc = GCState(trashed_ids={"r1"})
        result = apply_gc(messages, gc)
        assert "trashed by model" in result[2]["content"]
        assert "big file" not in result[2]["content"]

    def test_snippet_trims_content(self):
        messages = [
            {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": "line1\ndef main():\n    pass"},
        ]
        gc = GCState(snippets={"r1": {"id": "r1", "keep_after": "def main"}})
        result = apply_gc(messages, gc)
        assert "def main" in result[0]["content"]
        assert "line1" not in result[0]["content"]

    def test_trash_wins_over_snippet(self):
        gc = GCState(trashed_ids={"r1"}, snippets={"r1": {"id": "r1", "keep_after": "x"}})
        messages = [{"role": "tool", "tool_call_id": "r1", "name": "Read", "content": "data"}]
        result = apply_gc(messages, gc)
        assert "trashed" in result[0]["content"]

    def test_non_tool_messages_unchanged(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        gc = GCState(trashed_ids={"r1"})
        result = apply_gc(messages, gc)
        assert result[0]["content"] == "hello"
        assert result[1]["content"] == "world"

    def test_unaffected_tool_unchanged(self):
        messages = [
            {"role": "tool", "tool_call_id": "r2", "name": "Grep", "content": "grep results"},
        ]
        gc = GCState(trashed_ids={"r1"})
        result = apply_gc(messages, gc)
        assert result[0]["content"] == "grep results"

    def test_empty_gc_returns_same(self):
        messages = [{"role": "user", "content": "hi"}]
        gc = GCState()
        result = apply_gc(messages, gc)
        assert result is messages

    def test_original_not_mutated(self):
        messages = [
            {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": "original"},
        ]
        gc = GCState(trashed_ids={"r1"})
        apply_gc(messages, gc)
        assert messages[0]["content"] == "original"


class TestInjectNotes:
    def test_empty_notes(self):
        messages = [{"role": "user", "content": "hello"}]
        result = inject_notes(messages, {})
        assert result[0]["content"] == "hello"

    def test_injects_into_last_user_message(self):
        messages = [
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "next task"},
        ]
        notes = {"plan": "step 1: fix bug"}
        result = inject_notes(messages, notes)
        assert "working memory" in result[1]["content"].lower()
        assert "plan" in result[1]["content"]
        assert "step 1: fix bug" in result[1]["content"]
        assert "next task" in result[1]["content"]

    def test_original_not_mutated(self):
        messages = [{"role": "user", "content": "hello"}]
        inject_notes(messages, {"note": "content"})
        assert messages[0]["content"] == "hello"

    def test_multiple_notes(self):
        messages = [{"role": "user", "content": "go"}]
        notes = {"plan": "step 1", "context": "app.py"}
        result = inject_notes(messages, notes)
        assert "plan" in result[0]["content"]
        assert "context" in result[0]["content"]
        assert "step 1" in result[0]["content"]
        assert "app.py" in result[0]["content"]

    def test_no_user_message(self):
        messages = [{"role": "assistant", "content": "hi"}]
        result = inject_notes(messages, {"note": "content"})
        assert len(result) == 1
        assert "note" not in result[0].get("content", "")
