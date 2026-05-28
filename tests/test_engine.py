"""Tests for yflow.engine."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from yflow.engine import (
    build_workflow_prompt,
    classify_task,
    execute_workflow,
    instantiate_template,
    list_workflows,
    load_template,
    load_workflow,
    resolve_execution_order,
    validate_workflow,
    record_run,
)


class TestValidateWorkflow:
    def test_valid_minimal(self):
        data = {"name": "test", "steps": [{"id": "s1", "type": "command", "command": "echo hi"}]}
        assert validate_workflow(data) == []

    def test_missing_name(self):
        errors = validate_workflow({"steps": []})
        assert any("name" in e for e in errors)

    def test_missing_steps(self):
        errors = validate_workflow({"name": "test"})
        assert any("steps" in e for e in errors)

    def test_duplicate_ids(self):
        data = {
            "name": "test",
            "steps": [
                {"id": "dup", "type": "command", "command": "echo 1"},
                {"id": "dup", "type": "command", "command": "echo 2"},
            ],
        }
        errors = validate_workflow(data)
        assert any("duplicate" in e for e in errors)

    def test_unknown_type(self):
        data = {"name": "test", "steps": [{"id": "s1", "type": "invalid"}]}
        errors = validate_workflow(data)
        assert any("unknown type" in e for e in errors)

    def test_subagent_missing_context(self):
        data = {"name": "test", "steps": [{"id": "s1", "type": "subagent"}]}
        errors = validate_workflow(data)
        assert any("context" in e for e in errors)

    def test_missing_dep_reference(self):
        data = {
            "name": "test",
            "steps": [
                {"id": "s1", "type": "command", "command": "echo hi"},
                {"id": "s2", "type": "command", "command": "echo bye", "depends_on": "missing"},
            ],
        }
        errors = validate_workflow(data)
        assert any("referenced step" in e for e in errors)


class TestResolveExecutionOrder:
    def test_sequential(self):
        steps = [
            {"id": "a", "type": "command", "command": "1"},
            {"id": "b", "type": "command", "command": "2", "depends_on": "a"},
            {"id": "c", "type": "command", "command": "3", "depends_on": "b"},
        ]
        waves = resolve_execution_order(steps)
        assert len(waves) == 3  # Each in own wave
        assert waves[0] == ["a"]
        assert waves[1] == ["b"]
        assert waves[2] == ["c"]

    def test_parallel_independent(self):
        steps = [
            {"id": "a", "type": "command", "command": "1"},
            {"id": "b", "type": "command", "command": "2"},
            {"id": "c", "type": "command", "command": "3"},
        ]
        waves = resolve_execution_order(steps)
        assert len(waves) == 1  # All in one wave
        assert set(waves[0]) == {"a", "b", "c"}

    def test_mixed(self):
        steps = [
            {"id": "a", "type": "command", "command": "1"},
            {"id": "b", "type": "command", "command": "2"},
            {"id": "c", "type": "command", "command": "3", "depends_on": ["a", "b"]},
        ]
        waves = resolve_execution_order(steps)
        assert len(waves) == 2
        assert set(waves[0]) == {"a", "b"}
        assert waves[1] == ["c"]

    def test_list_dep(self):
        steps = [
            {"id": "a", "type": "command", "command": "1"},
            {"id": "b", "type": "command", "command": "2", "depends_on": ["a"]},
        ]
        waves = resolve_execution_order(steps)
        assert len(waves) == 2

    def test_circular_breaks(self):
        steps = [
            {"id": "a", "type": "command", "command": "1", "depends_on": "b"},
            {"id": "b", "type": "command", "command": "2", "depends_on": "a"},
        ]
        waves = resolve_execution_order(steps)
        # Circular: first wave empty → break
        assert len(waves) == 0


class TestClassifyTask:
    def test_flutter_bug(self):
        result = classify_task("Flutter app crash on startup bug fix")
        assert result["template"] == "flutter-bug-fix"

    def test_flutter_feature(self):
        result = classify_task("Add new Flutter feature for dark mode")
        assert result["template"] == "flutter-feature"

    def test_backend_bug(self):
        result = classify_task("API server crash bug fix")
        assert result["template"] == "backend-bug-fix"

    def test_backend_feature(self):
        result = classify_task("Add new backend feature for user auth")
        assert result["template"] == "backend-feature"

    def test_no_match(self):
        result = classify_task("do something random")
        assert result["template"] is None


class TestExecuteWorkflow:
    def test_native_command(self):
        workflow = {
            "name": "test",
            "steps": [
                {"id": "s1", "type": "command", "command": "echo hello world"}
            ],
        }
        result = execute_workflow(workflow)
        assert "s1" in result["local_outputs"]
        assert "hello world" in result["local_outputs"]["s1"]
        assert len(result["deferred_steps"]) == 0

    def test_variable_passing_between_steps(self):
        workflow = {
            "name": "test",
            "steps": [
                {"id": "first", "type": "command", "command": "echo step1-output"},
                {
                    "id": "second",
                    "type": "command",
                    "command": "echo got:$first.output",
                    "depends_on": "first",
                },
            ],
        }
        result = execute_workflow(workflow)
        assert "second" in result["local_outputs"]
        assert "step1-output" in result["local_outputs"]["second"]

    def test_subagent_provider_hermes_still_deferred(self):
        """provider: hermes preserves backward-compat defer-to-external behavior."""
        workflow = {
            "name": "test",
            "steps": [
                {"id": "s1", "type": "subagent", "provider": "hermes",
                 "context": "Do something via hermes"},
            ],
        }
        result = execute_workflow(workflow)
        assert len(result["deferred_steps"]) == 1
        assert result["deferred_steps"][0]["id"] == "s1"
        assert result["prompt"] != ""

    def test_subagent_defaults_to_reasonix_acp(self, monkeypatch):
        """subagent without provider attribute routes to reasonix ACP (not deferred)."""
        # Patch execute_reasonix_acp_step so it doesn't need reasonix CLI installed
        def fake_acp(step, session):
            session.capture(step["id"], "reasonix-acp-output")
            return "reasonix-acp-output"

        monkeypatch.setattr(
            "yflow.engine.execute_reasonix_acp_step", fake_acp
        )
        workflow = {
            "name": "test",
            "steps": [
                {"id": "s1", "type": "subagent",
                 "context": "Write a function to parse JSON"},
            ],
        }
        result = execute_workflow(workflow)
        # Should NOT be deferred — ran natively via reasonix ACP
        assert len(result["deferred_steps"]) == 0
        assert "s1" in result["local_outputs"]
        assert result["local_outputs"]["s1"] == "reasonix-acp-output"

    def test_subagent_explicit_reasonix_provider(self, monkeypatch):
        """Explicit provider: reasonix also routes to reasonix ACP."""
        def fake_acp(step, session):
            session.capture(step["id"], "explicit-reasonix-output")
            return "explicit-reasonix-output"

        monkeypatch.setattr(
            "yflow.engine.execute_reasonix_acp_step", fake_acp
        )
        workflow = {
            "name": "test",
            "steps": [
                {"id": "s1", "type": "subagent", "provider": "reasonix",
                 "context": "Refactor the auth module"},
            ],
        }
        result = execute_workflow(workflow)
        assert len(result["deferred_steps"]) == 0
        assert result["local_outputs"]["s1"] == "explicit-reasonix-output"

    def test_no_steps(self):
        workflow = {"name": "empty", "steps": []}
        result = execute_workflow(workflow)
        assert result["local_outputs"] == {}
        assert result["deferred_steps"] == []
        assert result["prompt"] == ""


class TestLoadWorkflow:
    def test_load_valid(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("name: test\nsteps:\n  - id: s1\n    type: command\n    command: echo hi\n")
            tmp = f.name
        try:
            wf = load_workflow(tmp)
            assert wf["name"] == "test"
            assert len(wf["steps"]) == 1
        finally:
            os.unlink(tmp)

    def test_load_invalid(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("name: test\nsteps: []\n")
            tmp = f.name
        try:
            wf = load_workflow(tmp)
            assert wf["name"] == "test"
        finally:
            os.unlink(tmp)

    def test_load_bad_syntax(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("name: [bad syntax\n")
            tmp = f.name
        try:
            with pytest.raises(Exception):
                load_workflow(tmp)
        finally:
            os.unlink(tmp)


class TestRecordRun:
    def test_record(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            hist = f.name
        try:
            record_run("test-wf", True, local_steps=2, history_file=hist)
            with open(hist) as f:
                line = f.readline()
            record = json.loads(line)
            assert record["workflow"] == "test-wf"
            assert record["success"] is True
            assert record["local_steps"] == 2
        finally:
            os.unlink(hist)
