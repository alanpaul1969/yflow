"""
Tests for v0.6.0 engine hooks: tools_allowlist, rules_file, scope enforcement.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yflow.boundary import ScopeViolation
from yflow.engine import (
    _apply_step_boundaries,
    _enforce_step_scope,
    _git_rev_porcelain,
    _diff_porcelain,
    execute_workflow,
    WorkflowSession,
)


class TestGitRevPorcelain(unittest.TestCase):
    def test_non_git_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_git_rev_porcelain(d), "")


class TestDiffPorcelain(unittest.TestCase):
    def test_no_changes(self):
        before = "M  foo.py\n"
        after = "M  foo.py\n"
        self.assertEqual(_diff_porcelain(before, after), [])

    def test_new_file_appears(self):
        before = "M  foo.py\n"
        after = "M  foo.py\nM  bar.py\n"
        self.assertEqual(_diff_porcelain(before, after), ["bar.py"])

    def test_handles_rename(self):
        before = ""
        after = "R  old.py -> new.py\n"
        self.assertEqual(_diff_porcelain(before, after), ["new.py"])

    def test_short_lines_ignored(self):
        before = "M\n"  # too short
        after = "M  real.py\n"
        self.assertEqual(_diff_porcelain(before, after), ["real.py"])


class TestApplyStepBoundaries(unittest.TestCase):
    def test_no_tools_no_rules_no_change(self):
        step = {"id": "s1", "prompt": "hello"}
        _apply_step_boundaries(step, base_dir=".")
        self.assertNotIn("_resolved_prompt", step)

    def test_tools_allowlist_injects_text(self):
        step = {"id": "s1", "prompt": "do thing", "tools": ["read"]}
        _apply_step_boundaries(step, base_dir=".")
        self.assertIn("_resolved_prompt", step)
        self.assertIn("TOOL BOUNDARY", step["_resolved_prompt"])
        self.assertIn("MANDATORY", step["_resolved_prompt"])
        # Original prompt should be preserved
        self.assertIn("do thing", step["_resolved_prompt"])

    def test_rules_file_injects_content(self):
        with tempfile.TemporaryDirectory() as d:
            rules = Path(d) / "AGENTS.md"
            rules.write_text("# My Rules\nBe good.\n")
            step = {"id": "s1", "prompt": "do thing", "rules_file": "./AGENTS.md"}
            _apply_step_boundaries(step, base_dir=d)
            self.assertIn("PROJECT RULES", step["_resolved_prompt"])
            self.assertIn("Be good", step["_resolved_prompt"])

    def test_missing_rules_file_logs_warning(self):
        step = {"id": "s1", "prompt": "do thing", "rules_file": "./nonexistent.md"}
        _apply_step_boundaries(step, base_dir=".")
        # Should not crash; should not inject
        self.assertNotIn("_resolved_prompt", step)

    def test_context_field_also_supported(self):
        step = {"id": "s1", "context": "do thing", "tools": ["read"]}
        _apply_step_boundaries(step, base_dir=".")
        self.assertIn("_resolved_context", step)


class TestEnforceStepScope(unittest.TestCase):
    def test_no_scope_no_op(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            # Init git
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
            # No scope declared → no check
            _enforce_step_scope(
                {"id": "s1", "scope": None},
                cwd=d,
                pre_step_porcelain="",
            )

    def test_scope_violation_raises(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
            # Create a file in frontend/ that step will "modify"
            Path(d, "frontend").mkdir()
            (Path(d) / "frontend" / "app.py").write_text("x")
            with self.assertRaises(ScopeViolation) as ctx:
                _enforce_step_scope(
                    {"id": "s1", "scope": ["backend/"]},
                    cwd=d,
                    pre_step_porcelain="",
                )
            self.assertEqual(ctx.exception.step_id, "s1")
            self.assertIn("frontend/app.py", ctx.exception.violations)

    def test_scope_compliant_passes(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
            Path(d, "backend").mkdir()
            (Path(d) / "backend" / "api.py").write_text("x")
            # Should not raise
            _enforce_step_scope(
                {"id": "s1", "scope": ["backend/"]},
                cwd=d,
                pre_step_porcelain="",
            )


class TestExecuteWorkflowWithNewStepTypes(unittest.TestCase):
    def test_human_checkpoint_writes_pending_in_non_tty(self):
        """Integration: non-TTY execution writes pending file."""
        from yflow.checkpoint import read_pending
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            # Make it a valid project (not git) — scope check is skipped
            workflow = {
                "name": "test-factory",
                "steps": [
                    {
                        "id": "check1",
                        "type": "human_checkpoint",
                        "message": "approve?",
                    },
                ],
            }
            with patch("sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = False
                mock_stdin.read.return_value = ""
                with self.assertRaises(SystemExit) as ctx:
                    execute_workflow(workflow)
                self.assertEqual(ctx.exception.code, 75)
            pending = read_pending("check1", cwd=d)
            self.assertIsNotNone(pending)
            self.assertEqual(pending["status"], "pending")


if __name__ == "__main__":
    unittest.main()
