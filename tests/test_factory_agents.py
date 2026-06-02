"""
Tests for yflow.agents.factory — acceptance_tests + implementation_validator.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from yflow.agents.factory import (
    _parse_acceptance_criteria,
    execute_acceptance_tests_step,
    execute_implementation_validator_step,
)
from yflow.engine import WorkflowSession


class TestParseAcceptanceCriteria(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_parse_acceptance_criteria(""), [])

    def test_bulleted_list(self):
        text = """
        # User Story
        Some text.

        ## Acceptance Criteria
        - criterion A
        - criterion B
        - criterion C
        """
        criteria = _parse_acceptance_criteria(text)
        self.assertEqual(len(criteria), 3)
        self.assertIn("criterion A", criteria[0])

    def test_numbered_list(self):
        text = """
        ## Acceptance Criteria
        1. first
        2. second
        """
        criteria = _parse_acceptance_criteria(text)
        self.assertEqual(len(criteria), 2)
        self.assertIn("first", criteria[0])

    def test_section_heading_required(self):
        text = """
        # Random
        - not in criteria section
        """
        self.assertEqual(_parse_acceptance_criteria(text), [])


class TestAcceptanceTestsStep(unittest.TestCase):
    def _make_session(self):
        s = WorkflowSession({})
        s.capture("write-stories", """
        ## Acceptance Criteria
        - user can log in
        - user gets a token
        """)
        return s

    def test_no_source_uses_empty_criteria(self):
        s = WorkflowSession({})
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            with patch("yflow.agents.factory.get_git_changed_files", return_value=[]):
                output = execute_acceptance_tests_step(
                    {"id": "t1", "test_command": "pytest", "source": "write-stories"},
                    s,
                )
        verdict = json.loads(output)
        self.assertEqual(verdict["test_passed"], True)
        self.assertEqual(verdict["scope_clean"], True)

    def test_failing_test_marks_not_passed(self):
        s = self._make_session()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="FAILED", stderr="")
            with patch("yflow.agents.factory.get_git_changed_files", return_value=[]):
                output = execute_acceptance_tests_step(
                    {"id": "t1", "test_command": "pytest", "source": "write-stories"},
                    s,
                )
        verdict = json.loads(output)
        self.assertFalse(verdict["test_passed"])

    def test_scope_violation_raises(self):
        from yflow.boundary import ScopeViolation
        s = self._make_session()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            with patch(
                "yflow.agents.factory.get_git_changed_files",
                return_value=["backend/api.py"],  # outside may_modify
            ):
                with self.assertRaises(ScopeViolation) as ctx:
                    execute_acceptance_tests_step(
                        {
                            "id": "t1",
                            "test_command": "pytest",
                            "source": "write-stories",
                            "may_modify": ["tests/**"],
                        },
                        s,
                    )
                self.assertEqual(ctx.exception.step_id, "t1")
                self.assertIn("backend/api.py", ctx.exception.violations)


class TestImplementationValidatorStep(unittest.TestCase):
    def _make_session(self, story=""):
        s = WorkflowSession({})
        if story:
            s.capture("write-stories", story)
        return s

    def test_no_story_runs_without_criteria(self):
        s = self._make_session()
        with patch("yflow.agents.factory.get_git_changed_files", return_value=[]):
            output = execute_implementation_validator_step(
                {"id": "v1", "checks": ["scope"]},
                s,
            )
        verdict = json.loads(output)
        self.assertEqual(verdict["criteria_count"], 0)
        self.assertEqual(verdict["verdict"], "PASS")

    def test_criteria_check_finds_uncovered(self):
        story = """
        ## Acceptance Criteria
        - user can authenticate via OAuth
        """
        s = self._make_session(story)
        with patch("yflow.agents.factory.get_git_changed_files", return_value=[]):
            output = execute_implementation_validator_step(
                {"id": "v1", "checks": ["criteria"], "story_ref": "write-stories"},
                s,
            )
        verdict = json.loads(output)
        # No test files in changes → criterion is uncovered
        important = [f for f in verdict["findings"] if f["severity"] == "important"]
        self.assertGreater(len(important), 0)

    def test_security_check_finds_secret(self):
        with tempfile.TemporaryDirectory() as d:
            # Create a file with a hardcoded secret
            os.chdir(d)
            (Path(d) / "config.py").write_text(
                'api_key = "sk-abcdef1234567890abcdef1234"\n'
            )
            s = WorkflowSession({})
            with patch(
                "yflow.agents.factory.get_git_changed_files",
                return_value=["config.py"],
            ):
                output = execute_implementation_validator_step(
                    {"id": "v1", "checks": ["security"]},
                    s,
                )
            verdict = json.loads(output)
            critical = [f for f in verdict["findings"] if f["severity"] == "critical"]
            self.assertGreater(len(critical), 0)
            self.assertEqual(verdict["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main()
