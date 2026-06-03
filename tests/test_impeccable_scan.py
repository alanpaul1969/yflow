"""
Tests for the impeccable (anti-pattern) scan integration.

Confirms the deterministic Flutter scanner can be called from
implementation_validator's "design" check.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yflow.agents.factory import execute_implementation_validator_step
from yflow.engine import WorkflowSession
from yflow.impeccable_scan import scan_project, print_report, RULES, MATCHERS


class TestImpeccableScanDirect(unittest.TestCase):
    def test_empty_project_no_tells(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            results = scan_project(Path(d))
            self.assertEqual(len(results), len(RULES))
            for rule_id, data in results.items():
                self.assertEqual(data["files"], [])

    def test_ghost_card_detected(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "lib").mkdir()
            (Path(d) / "lib" / "card.dart").write_text(
                "Container(\n"
                "  decoration: BoxDecoration(\n"
                "    border: Border.all(color: Colors.black),\n"
                "    boxShadow: [BoxShadow(blurRadius: 24)],\n"
                "  ),\n"
                ")\n"
            )
            results = scan_project(Path(d))
            # Ghost card should be flagged
            self.assertGreater(len(results["ghost-card"]["files"]), 0)

    def test_over_rounded_detected(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "lib").mkdir()
            (Path(d) / "lib" / "card.dart").write_text(
                "Container(\n"
                "  decoration: BoxDecoration(\n"
                "    borderRadius: BorderRadius.circular(32),\n"
                "  ),\n"
                ")\n"
            )
            results = scan_project(Path(d))
            self.assertGreater(len(results["over-rounded"]["files"]), 0)

    def test_gradient_text_detected(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "lib").mkdir()
            (Path(d) / "lib" / "hero.dart").write_text(
                "ShaderMask(\n"
                "  shaderCallback: (bounds) => LinearGradient(...).createShader(bounds),\n"
                "  child: Text('Hello'),\n"
                ")\n"
            )
            results = scan_project(Path(d))
            self.assertGreater(len(results["gradient-text"]["files"]), 0)

    def test_glassmorphism_detected(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "lib").mkdir()
            (Path(d) / "lib" / "glass.dart").write_text(
                "BackdropFilter(\n"
                "  filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),\n"
                "  child: Container(),\n"
                ")\n"
            )
            results = scan_project(Path(d))
            self.assertGreater(len(results["glassmorphism-default"]["files"]), 0)


class TestDesignCheckInValidator(unittest.TestCase):
    def _make_session(self):
        return WorkflowSession({})

    def test_design_check_finds_glassmorphism(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
            (Path(d) / "lib").mkdir()
            (Path(d) / "lib" / "card.dart").write_text(
                "BackdropFilter(\n"
                "  filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),\n"
                "  child: Container(),\n"
                ")\n"
            )
            with patch("yflow.agents.factory.get_git_changed_files",
                       return_value=["lib/card.dart"]):
                output = execute_implementation_validator_step(
                    {"id": "v1", "checks": ["design"]},
                    self._make_session(),
                )
            verdict = json.loads(output)
            design_findings = [f for f in verdict["findings"] if f["check"] == "design"]
            self.assertGreater(len(design_findings), 0)
            self.assertEqual(design_findings[0]["rule_id"], "glassmorphism-default")
            self.assertEqual(design_findings[0]["severity"], "medium")

    def test_design_check_skips_non_design_files(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
            (Path(d) / "lib").mkdir()
            # Python file — should be skipped by design check
            (Path(d) / "lib" / "logic.py").write_text(
                "BackdropFilter(\n"  # would match if scanned
                "  filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),\n"
                ")\n"
            )
            with patch("yflow.agents.factory.get_git_changed_files",
                       return_value=["lib/logic.py"]):
                output = execute_implementation_validator_step(
                    {"id": "v1", "checks": ["design"]},
                    self._make_session(),
                )
            verdict = json.loads(output)
            design_findings = [f for f in verdict["findings"] if f["check"] == "design"]
            self.assertEqual(len(design_findings), 0)


if __name__ == "__main__":
    unittest.main()
