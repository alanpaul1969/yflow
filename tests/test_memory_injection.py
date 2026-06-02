"""
Tests for yflow memory injection — cold_load building, validation, budget.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from yflow.memory.stdlib_backend import StdlibBackend
from yflow.memory_injection import (
    build_cold_context,
    validate_memory_section,
    check_budget,
)


class TestBuildColdContext(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="yflow-coldctx-"))
        self.backend = StdlibBackend(root=self.tmp)
        self.backend.add("a", body="Content of A", title="A")
        self.backend.add("infra/b", body="Content of B", title="B")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_returns_empty(self):
        self.assertEqual(build_cold_context([], root=self.tmp), "")

    def test_single_slug(self):
        out = build_cold_context(["a"], root=self.tmp)
        self.assertIn("# === a ===", out)
        self.assertIn("Content of A", out)
        self.assertIn("Cold memory (auto-injected from yflow memory)", out)

    def test_multiple_slugs(self):
        out = build_cold_context(["a", "infra/b"], root=self.tmp)
        self.assertIn("=== a ===", out)
        self.assertIn("=== infra/b ===", out)

    def test_missing_slug_marks(self):
        out = build_cold_context(["nonexistent"], root=self.tmp)
        self.assertIn("[missing: nonexistent not found in memory]", out)


class TestValidateMemorySection(unittest.TestCase):
    def test_valid_empty(self):
        self.assertEqual(validate_memory_section({}), [])

    def test_valid_full(self):
        errs = validate_memory_section({
            "cold_load": ["a", "b/c"],
            "budget_chars": 1800,
            "markers": ["★", "[!]"],
        })
        self.assertEqual(errs, [])

    def test_cold_load_must_be_list(self):
        errs = validate_memory_section({"cold_load": "not a list"})
        self.assertEqual(len(errs), 1)
        self.assertIn("must be a list", errs[0])

    def test_cold_load_invalid_slug(self):
        errs = validate_memory_section({"cold_load": [None, 123]})
        self.assertEqual(len(errs), 2)

    def test_budget_must_be_int(self):
        errs = validate_memory_section({"budget_chars": "abc"})
        self.assertEqual(len(errs), 1)

    def test_budget_must_be_nonnegative(self):
        errs = validate_memory_section({"budget_chars": -100})
        self.assertEqual(len(errs), 1)

    def test_markers_must_be_list(self):
        errs = validate_memory_section({"markers": "★"})
        self.assertEqual(len(errs), 1)


class TestCheckBudget(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="yflow-budget-"))
        self.backend = StdlibBackend(root=self.tmp)
        # 100 chars total
        self.backend.add("small", body="X" * 50, title="small")
        # 200 chars total
        self.backend.add("big", body="X" * 150, title="big")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty(self):
        total, ok = check_budget([], 100, root=self.tmp)
        self.assertEqual(total, 0)
        self.assertTrue(ok)

    def test_within_budget(self):
        total, ok = check_budget(["small"], 500, root=self.tmp)
        # Small entry should be ~80-100 chars (body + frontmatter)
        self.assertTrue(ok)
        self.assertGreater(total, 0)

    def test_over_budget(self):
        total, ok = check_budget(["small", "big"], 100, root=self.tmp)
        self.assertFalse(ok)
        # Total should be ~280+ chars (over 100)
        self.assertGreater(total, 100)

    def test_missing_slug_counted_as_zero(self):
        total, ok = check_budget(["nonexistent"], 100, root=self.tmp)
        self.assertEqual(total, 0)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
