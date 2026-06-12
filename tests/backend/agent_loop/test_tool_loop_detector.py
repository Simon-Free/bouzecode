# [desc] Unit tests for ToolCallLoopDetector cycle detection, reset, and edge cases. [/desc]
"""Tests for agent.loop_detector — Tool Call Loop Detection."""
import unittest

from bouzecode.backend.agent.loop_detector import ToolCallLoopDetector


class TestToolCallLoopDetector(unittest.TestCase):

    def setUp(self):
        self.detector = ToolCallLoopDetector()

    def test_no_detection_with_varied_calls(self):
        for i in range(20):
            self.detector.record_turn([{"name": f"Tool{i}", "input": {"x": str(i)}}])
        self.assertIsNone(self.detector.check())

    def test_cycle_size_1(self):
        tc = [{"name": "Read", "input": {"file_path": "/foo.py"}}]
        for _ in range(3):
            self.detector.record_turn(tc)
            result = self.detector.check()
        self.assertIsNotNone(result)
        self.assertEqual(result.cycle_size, 1)
        self.assertEqual(result.repeats, 3)

    def test_cycle_size_2(self):
        a = [{"name": "Read", "input": {"file_path": "/a.py"}}]
        b = [{"name": "Write", "input": {"file_path": "/b.py"}}]
        for _ in range(3):
            self.detector.record_turn(a)
            self.detector.record_turn(b)
        result = self.detector.check()
        self.assertIsNotNone(result)
        self.assertEqual(result.cycle_size, 2)

    def test_cycle_size_3(self):
        calls = [
            [{"name": "Read", "input": {"file_path": "/a.py"}}],
            [{"name": "Grep", "input": {"pattern": "x", "path": "/src"}}],
            [{"name": "Bash", "input": {"command": "echo hi"}}],
        ]
        for _ in range(3):
            for c in calls:
                self.detector.record_turn(c)
        result = self.detector.check()
        self.assertIsNotNone(result)
        self.assertEqual(result.cycle_size, 3)

    def test_different_params_no_detection(self):
        for i in range(10):
            self.detector.record_turn([{"name": "Read", "input": {"file_path": f"/file{i}.py"}}])
        self.assertIsNone(self.detector.check())

    def test_reset_clears_history(self):
        tc = [{"name": "Read", "input": {"file_path": "/foo.py"}}]
        for _ in range(3):
            self.detector.record_turn(tc)
        self.detector.reset()
        self.assertIsNone(self.detector.check())

    def test_empty_tool_calls(self):
        self.detector.record_turn([])
        self.assertIsNone(self.detector.check())

    def test_multi_tool_turn(self):
        tc = [
            {"name": "Read", "input": {"file_path": "/a.py"}},
            {"name": "Read", "input": {"file_path": "/b.py"}},
        ]
        for _ in range(3):
            self.detector.record_turn(tc)
        result = self.detector.check()
        self.assertIsNotNone(result)
        self.assertEqual(result.cycle_size, 1)

    def test_near_miss_not_enough_repeats(self):
        tc = [{"name": "Read", "input": {"file_path": "/foo.py"}}]
        for _ in range(2):
            self.detector.record_turn(tc)
        self.assertIsNone(self.detector.check())

    def test_record_and_check_combined(self):
        tc = [{"name": "Bash", "input": {"command": "ls"}}]
        result = None
        for _ in range(3):
            result = self.detector.record_and_check(tc)
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
