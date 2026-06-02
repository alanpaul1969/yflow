"""
Tests for yflow.checkpoint — human-in-the-loop checkpoint.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from yflow.checkpoint import (
    EX_DEFERRED,
    CheckpointDecision,
    execute_checkpoint,
    list_pending,
    read_pending,
    resolve_pending,
    write_pending,
)


@contextmanager
def temp_cwd():
    """Run a block with cwd changed to a temp dir, then restore."""
    old = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            yield d
        finally:
            os.chdir(old)


@contextmanager
def fake_stdin(text: str):
    """Replace stdin with a string buffer."""
    old = sys.stdin
    sys.stdin = io.StringIO(text)
    try:
        yield
    finally:
        sys.stdin = old


@contextmanager
def fake_tty(is_tty: bool):
    """Force sys.stdin.isatty() to return a specific value."""
    old_isatty = sys.stdin.isatty

    def _fake():
        return is_tty

    sys.stdin.isatty = _fake
    try:
        yield
    finally:
        sys.stdin.isatty = old_isatty


class TestWriteReadPending(unittest.TestCase):
    def test_roundtrip(self):
        with temp_cwd() as d:
            path = write_pending(
                "review-stories",
                "Please review",
                workflow="my-workflow",
                metadata={"foo": "bar"},
            )
            self.assertTrue(path.exists())
            payload = read_pending("review-stories", cwd=d)
            self.assertEqual(payload["step_id"], "review-stories")
            self.assertEqual(payload["workflow"], "my-workflow")
            self.assertEqual(payload["status"], "pending")
            self.assertEqual(payload["metadata"]["foo"], "bar")

    def test_read_missing_returns_none(self):
        with temp_cwd() as d:
            self.assertIsNone(read_pending("nonexistent", cwd=d))


class TestResolvePending(unittest.TestCase):
    def test_approve(self):
        with temp_cwd() as d:
            write_pending("step1", "msg", workflow="wf", cwd=d)
            payload = resolve_pending("step1", "approve", cwd=d, reviewer="alice")
            self.assertEqual(payload["status"], "approved")
            self.assertEqual(payload["reviewer"], "alice")

    def test_reject(self):
        with temp_cwd() as d:
            write_pending("step1", "msg", workflow="wf", cwd=d)
            payload = resolve_pending("step1", "reject", cwd=d, note="needs work")
            self.assertEqual(payload["status"], "rejected")
            self.assertEqual(payload["note"], "needs work")

    def test_missing_raises(self):
        with temp_cwd():
            with self.assertRaises(FileNotFoundError):
                resolve_pending("nope", "approve")


class TestListPending(unittest.TestCase):
    def test_empty(self):
        with temp_cwd() as d:
            self.assertEqual(list_pending(cwd=d), [])

    def test_returns_all(self):
        with temp_cwd() as d:
            write_pending("a", "msg1", workflow="wf1", cwd=d)
            write_pending("b", "msg2", workflow="wf2", cwd=d)
            pending = list_pending(cwd=d)
            self.assertEqual(len(pending), 2)
            ids = {p["step_id"] for p in pending}
            self.assertEqual(ids, {"a", "b"})


class TestExecuteCheckpointInteractive(unittest.TestCase):
    def test_tty_approve_continues(self):
        with temp_cwd() as d, fake_stdin("a\n"), fake_tty(True):
            # Should return without raising
            execute_checkpoint(
                {"id": "cp1", "message": "Review?"},
                workflow_name="wf",
                cwd=d,
            )

    def test_tty_reject_raises(self):
        with temp_cwd() as d, fake_stdin("r\nnot good\n"), fake_tty(True):
            with self.assertRaises(CheckpointDecision) as ctx:
                execute_checkpoint(
                    {"id": "cp1", "message": "Review?"},
                    workflow_name="wf",
                    cwd=d,
                )
            self.assertEqual(ctx.exception.step_id, "cp1")
            self.assertIn("not good", ctx.exception.reason)


class TestExecuteCheckpointNonInteractive(unittest.TestCase):
    def test_non_tty_writes_pending_and_exits(self):
        with temp_cwd() as d, fake_stdin(""), fake_tty(False):
            with self.assertRaises(SystemExit) as ctx:
                execute_checkpoint(
                    {"id": "cp-async", "message": "Please review"},
                    workflow_name="my-wf",
                    cwd=d,
                )
            self.assertEqual(ctx.exception.code, EX_DEFERRED)
            # Pending file should be created
            payload = read_pending("cp-async", cwd=d)
            self.assertIsNotNone(payload)
            self.assertEqual(payload["workflow"], "my-wf")
            self.assertEqual(payload["status"], "pending")


class TestProgressLogInPendingFile(unittest.TestCase):
    """Pending file should include a progress_log so reviewers can pick up
    where they left off after a long delay."""

    def test_progress_log_persisted(self):
        with temp_cwd() as d, fake_stdin(""), fake_tty(False):
            progress_log = {
                "workflow_name": "test-wf",
                "completed_steps": [{"id": "s1", "type": "subagent", "output_preview": "hello"}],
                "current_step": {"id": "cp", "type": "human_checkpoint", "message": "review?"},
                "remaining_steps": [{"id": "s2", "type": "subagent"}],
                "resume_command": "yflow checkpoint approve cp",
                "files_modified": [],
            }
            with self.assertRaises(SystemExit):
                execute_checkpoint(
                    {"id": "cp", "message": "review?"},
                    workflow_name="test-wf",
                    cwd=d,
                    progress_log=progress_log,
                )
            payload = read_pending("cp", cwd=d)
            self.assertIsNotNone(payload)
            self.assertIn("progress_log", payload)
            self.assertEqual(payload["progress_log"]["workflow_name"], "test-wf")
            self.assertEqual(len(payload["progress_log"]["completed_steps"]), 1)
            self.assertEqual(payload["progress_log"]["resume_command"],
                             "yflow checkpoint approve cp")

    def test_no_progress_log_still_works(self):
        with temp_cwd() as d, fake_stdin(""), fake_tty(False):
            with self.assertRaises(SystemExit):
                execute_checkpoint(
                    {"id": "cp", "message": "review?"},
                    workflow_name="test-wf",
                    cwd=d,
                    # no progress_log
                )
            payload = read_pending("cp", cwd=d)
            self.assertIsNotNone(payload)
            # No progress_log key when not provided
            self.assertNotIn("progress_log", payload)


if __name__ == "__main__":
    unittest.main()
