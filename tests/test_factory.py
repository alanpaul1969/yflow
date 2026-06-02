"""
Tests for yflow.factory — factory init CLI scaffold.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from yflow.factory import init_factory


class TestInitFactory(unittest.TestCase):
    def test_creates_workflow_file(self):
        with tempfile.TemporaryDirectory() as d:
            created = init_factory("myproj", out_dir=d)
            self.assertTrue(created["workflow"].exists())
            content = created["workflow"].read_text()
            self.assertIn("myproj", content)
            self.assertIn("7-Agent", content)

    def test_creates_agents_md(self):
        with tempfile.TemporaryDirectory() as d:
            created = init_factory("myproj", out_dir=d)
            self.assertTrue(created["agents"].exists())
            content = created["agents"].read_text()
            self.assertIn("Code style", content)
            self.assertIn("Boundaries", content)

    def test_does_not_clobber_existing_agents_md(self):
        with tempfile.TemporaryDirectory() as d:
            # Pre-create AGENTS.md with custom content
            existing = Path(d) / "AGENTS.md"
            existing.write_text("# My Custom Rules")
            created = init_factory("myproj", out_dir=d)
            # Should still exist with original content
            self.assertEqual(existing.read_text(), "# My Custom Rules")
            # But workflow should still be created
            self.assertTrue(created["workflow"].exists())

    def test_creates_checkpoints_dir(self):
        with tempfile.TemporaryDirectory() as d:
            created = init_factory("myproj", out_dir=d)
            self.assertTrue(created["checkpoints_dir"].exists())
            self.assertTrue((created["checkpoints_dir"] / ".gitkeep").exists())

    def test_creates_workflows_subdir(self):
        with tempfile.TemporaryDirectory() as d:
            created = init_factory("myproj", out_dir=d)
            self.assertTrue(created["workflow"].parent.name == "workflows")


if __name__ == "__main__":
    unittest.main()
