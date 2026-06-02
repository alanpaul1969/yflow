"""
Tests for _build_progress_log — the engine helper that snapshots
workflow state into the pending checkpoint file.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yflow.engine import WorkflowSession, _build_progress_log


class TestBuildProgressLog(unittest.TestCase):
    def test_basic_structure(self):
        workflow = {
            "name": "test-factory",
            "description": "An example",
            "steps": [
                {"id": "research", "type": "subagent", "prompt": "..."},
                {"id": "write-spec", "type": "subagent", "prompt": "..."},
                {"id": "review", "type": "human_checkpoint", "message": "OK?"},
                {"id": "build", "type": "subagent", "prompt": "..."},
            ],
        }
        current = {"id": "review", "type": "human_checkpoint", "message": "OK?"}
        session = WorkflowSession({})
        log = _build_progress_log(workflow, current, session, pre_step_porcelain="")
        self.assertEqual(log["workflow_name"], "test-factory")
        self.assertEqual(log["current_step"]["id"], "review")
        self.assertEqual(log["step_index"], 3)
        self.assertEqual(log["total_steps"], 4)
        self.assertEqual(len(log["completed_steps"]), 2)
        self.assertEqual(len(log["remaining_steps"]), 1)
        self.assertEqual(log["remaining_steps"][0]["id"], "build")
        self.assertIn("approve", log["resume_command"])

    def test_completed_steps_carry_output_preview(self):
        workflow = {
            "name": "wf",
            "steps": [
                {"id": "s1", "type": "command"},
                {"id": "cp", "type": "human_checkpoint"},
            ],
        }
        current = {"id": "cp", "type": "human_checkpoint"}
        session = WorkflowSession({})
        session.capture("s1", "x" * 1000)  # 1000 chars
        log = _build_progress_log(workflow, current, session, pre_step_porcelain="")
        preview = log["completed_steps"][0]["output_preview"]
        # 300 chars + ellipsis
        self.assertLessEqual(len(preview), 305)
        self.assertIn("…", preview)
        self.assertEqual(log["completed_steps"][0]["output_bytes"], 1000)

    def test_files_modified_count_from_git(self):
        import sys
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
            # Create a file BEFORE workflow started (part of pre-step baseline)
            (Path(d) / "before.py").write_text("x")
            # Capture the pre-step porcelain state (BEFORE the new file)
            pre = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=d, capture_output=True, text=True, check=True,
            ).stdout
            # Now simulate a step creating a new file
            (Path(d) / "after.py").write_text("y")
            workflow = {
                "name": "wf",
                "cwd": d,
                "steps": [
                    {"id": "s1", "type": "command"},
                    {"id": "cp", "type": "human_checkpoint"},
                ],
            }
            current = {"id": "cp", "type": "human_checkpoint"}
            session = WorkflowSession({})
            log = _build_progress_log(workflow, current, session, pre)
            self.assertIn("after.py", log["files_modified"])
            self.assertNotIn("before.py", log["files_modified"])

    def test_no_git_repo_graceful(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            workflow = {
                "name": "wf",
                "cwd": d,
                "steps": [{"id": "cp", "type": "human_checkpoint"}],
            }
            current = {"id": "cp", "type": "human_checkpoint"}
            session = WorkflowSession({})
            log = _build_progress_log(workflow, current, session, pre_step_porcelain="")
            self.assertEqual(log["files_modified"], [])

    def test_reject_command_format(self):
        workflow = {
            "name": "wf",
            "steps": [{"id": "cp", "type": "human_checkpoint"}],
        }
        current = {"id": "cp", "type": "human_checkpoint"}
        session = WorkflowSession({})
        log = _build_progress_log(workflow, current, session, pre_step_porcelain="")
        self.assertIn("reject", log["reject_command"])
        self.assertIn("cp", log["reject_command"])
        self.assertTrue(log["rejection_aborts_workflow"])


if __name__ == "__main__":
    unittest.main()
