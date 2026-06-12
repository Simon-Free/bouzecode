# [desc] Tests for LoopDetector ensuring real infinite loops are caught without false positives on normal text. [/desc]
"""Tests for LoopDetector — ensures real loops are caught, false positives are not."""

from bouzecode.backend.agent.thinking_parser import LoopDetector


def test_catches_real_loop():
    """A genuine infinite loop (same pattern repeated 50+ times) must be detected."""
    detector = LoopDetector()
    pattern = "This is a repeating block of text. " * 100
    assert detector.feed(pattern) is True


def test_catches_short_repeated_block():
    """A 25-char pattern repeated 8+ times must be detected."""
    detector = LoopDetector()
    pattern = "abcdefghijklmnopqrstuvwxy" * 20  # 25 chars * 20 repeats
    assert detector.feed(pattern) is True


def test_no_false_positive_on_analytical_text():
    """Realistic analytical text with repeated terms should NOT trigger."""
    detector = LoopDetector()
    text = """
    Looking at sse_subscribe() lines 19-31, the subscribe method calls task_manager.subscribe
    which acquires the lock. The subscribe method checks if cursor < len(events). If not,
    it calls wait(timeout=1.0). During the wait, push_event can fire notify_all. The subscribe
    method then returns events. The sse_subscribe loop checks is_running and yields keepalive.
    Next iteration calls subscribe again. The subscribe method acquires the lock again.
    If events arrived, subscribe returns them. Otherwise subscribe waits again.
    The sse_subscribe function yields the events as SSE. The subscribe pattern is safe because
    the Condition variable properly synchronizes push_event and subscribe calls.
    """
    assert detector.feed(text) is False


def test_no_false_positive_on_code_analysis():
    """Code with repeated function names should NOT trigger."""
    detector = LoopDetector()
    text = """
    def subscribe(self, task_id, cursor=0, timeout=1.0):
        with self._lock:
            task = self._tasks.get(task_id)
        if not task:
            return [], cursor
        with task._notify:
            if cursor < len(task.events):
                new_events = task.events[cursor:]
                return new_events, cursor + len(new_events)
            if task.status != TaskStatus.RUNNING:
                return [], cursor
            task._notify.wait(timeout=1.0)
            new_events = task.events[cursor:]
            return new_events, cursor + len(new_events)

    def push_event(self, task_id, event):
        with self._lock:
            task = self._tasks.get(task_id)
        if not task:
            return
        with task._notify:
            task.events.append(event)
            task._notify.notify_all()
    """
    assert detector.feed(text) is False


def test_no_false_positive_on_table():
    """Tabular data with repeated structure should NOT trigger."""
    detector = LoopDetector()
    rows = [f"| scenario_{i} | {'Yes' if i % 2 == 0 else 'No'} | {'Clean' if i % 3 == 0 else 'Retry'} |"
            for i in range(20)]
    text = "| Scenario | Events? | Client? |\n|---|---|---|\n" + "\n".join(rows)
    assert detector.feed(text) is False


def test_small_input_not_checked():
    """Inputs under 200 chars should never trigger, even if repetitive."""
    detector = LoopDetector()
    text = "ab" * 50  # 100 chars, very repetitive but under threshold
    assert detector.feed(text) is False


def test_incremental_feeding():
    """Loop detected even when fed incrementally."""
    detector = LoopDetector()
    pattern = "x" * 25
    for _ in range(20):
        result = detector.feed(pattern)
    assert result is True


def test_pattern_too_short_not_detected():
    """Short semi-random text should not false-positive."""
    detector = LoopDetector()
    # Feed text that has some local repetition but no real loop at pattern >= 20
    text = "".join(f"item_{i}: value_{i % 7}, " for i in range(80))
    assert detector.feed(text) is False
