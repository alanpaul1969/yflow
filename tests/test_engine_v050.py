"""
Tests for engine changes: memory: section validation, minimax step type,
cold memory propagation.
"""

from __future__ import annotations

import unittest

from yflow.engine import validate_workflow, STEP_TYPES


class TestValidateMemorySection(unittest.TestCase):
    def test_minimal_valid(self):
        errs = validate_workflow({
            "name": "x",
            "memory": {"cold_load": ["a", "b"]},
            "steps": [],
        })
        self.assertEqual(errs, [])

    def test_memory_cold_load_must_be_list(self):
        errs = validate_workflow({
            "name": "x",
            "memory": {"cold_load": "not a list"},
            "steps": [],
        })
        self.assertEqual(len(errs), 1)
        self.assertIn("cold_load", errs[0])

    def test_memory_budget_must_be_int(self):
        errs = validate_workflow({
            "name": "x",
            "memory": {"budget_chars": "abc"},
            "steps": [],
        })
        self.assertEqual(len(errs), 1)
        self.assertIn("budget_chars", errs[0])

    def test_markers_must_be_list(self):
        errs = validate_workflow({
            "name": "x",
            "memory": {"markers": "★"},
            "steps": [],
        })
        self.assertEqual(len(errs), 1)
        self.assertIn("markers", errs[0])


class TestMinimaxStepType(unittest.TestCase):
    def test_minimax_in_step_types(self):
        self.assertIn("minimax", STEP_TYPES)

    def test_minimax_requires_prompt_or_context(self):
        errs = validate_workflow({
            "name": "x",
            "steps": [{"id": "s1", "type": "minimax"}],
        })
        self.assertTrue(any("minimax" in e and "prompt" in e for e in errs))

    def test_minimax_with_prompt_valid(self):
        errs = validate_workflow({
            "name": "x",
            "steps": [{"id": "s1", "type": "minimax", "prompt": "do thing"}],
        })
        self.assertEqual(errs, [])

    def test_minimax_with_context_valid(self):
        errs = validate_workflow({
            "name": "x",
            "steps": [{"id": "s1", "type": "minimax", "context": "do thing"}],
        })
        self.assertEqual(errs, [])


if __name__ == "__main__":
    unittest.main()
