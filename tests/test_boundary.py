"""
Tests for yflow.boundary — tool allowlist + scope enforcement.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yflow.boundary import (
    ALL_KNOWN_TOOLS,
    ScopeViolation,
    build_rules_text,
    build_tools_allowlist_text,
    check_scope,
    enforce_scope,
    load_rules_file,
)


class TestBuildToolsAllowlistText(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(build_tools_allowlist_text([]), "")

    def test_includes_all_allowed_tools(self):
        text = build_tools_allowlist_text(["read", "search_files"])
        self.assertIn("`read`", text)
        self.assertIn("`search_files`", text)
        self.assertIn("MANDATORY", text)

    def test_includes_forbidden_list(self):
        text = build_tools_allowlist_text(["read"])
        # All known tools except 'read' should appear as forbidden
        self.assertIn("`write`", text)
        self.assertIn("`shell`", text)
        self.assertIn("`delete`", text)
        # 'read' itself should NOT appear in forbidden
        forbidden_section = text.split("MUST NOT use any of:")[1]
        self.assertNotIn("`read`", forbidden_section)

    def test_warns_agent_to_stop_if_needed_tool(self):
        text = build_tools_allowlist_text(["read"])
        self.assertIn("STOP and report", text)


class TestLoadRulesFile(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(load_rules_file("/nonexistent/AGENTS.md"), "")

    def test_loads_existing_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Project Rules\n\nBe excellent.\n")
            path = f.name
        try:
            content = load_rules_file(path)
            self.assertIn("Project Rules", content)
            self.assertIn("Be excellent", content)
        finally:
            os.unlink(path)

    def test_relative_path_resolved_against_base(self):
        with tempfile.TemporaryDirectory() as d:
            rules = Path(d) / "AGENTS.md"
            rules.write_text("# Rules")
            content = load_rules_file("./AGENTS.md", base_dir=d)
            self.assertEqual(content, "# Rules")

    def test_handles_oserror_gracefully(self):
        with patch("pathlib.Path.read_text", side_effect=OSError("perm denied")):
            self.assertEqual(load_rules_file("/some/path"), "")


class TestBuildRulesText(unittest.TestCase):
    def test_wraps_with_header(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("rule 1")
            path = f.name
        try:
            text = build_rules_text(path)
            self.assertIn("PROJECT RULES", text)
            self.assertIn("auto-injected", text)
            self.assertIn("rule 1", text)
        finally:
            os.unlink(path)

    def test_empty_when_file_missing(self):
        text = build_rules_text("/nonexistent.md")
        self.assertEqual(text, "")

    def test_register_brand_injects_brand_tells(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Design\n\n## Register\n\nbrand\n\n## Color\nOKLCH\n")
            path = f.name
        try:
            text = build_rules_text(path)
            self.assertIn("PROJECT RULES", text)
            self.assertIn("Register: BRAND", text)
            self.assertIn("Cream/sand/parchment", text)  # brand tell
        finally:
            os.unlink(path)

    def test_register_product_injects_product_tells(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Product\n\n## Register\n\nproduct\n\n")
            path = f.name
        try:
            text = build_rules_text(path)
            self.assertIn("Register: PRODUCT", text)
            self.assertIn("Decorative motion", text)  # product tell
            self.assertNotIn("Register: BRAND", text)
        finally:
            os.unlink(path)

    def test_no_register_neutral(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Random\n\nNo register here.\n")
            path = f.name
        try:
            text = build_rules_text(path)
            self.assertIn("PROJECT RULES", text)
            self.assertNotIn("Register: BRAND", text)
            self.assertNotIn("Register: PRODUCT", text)
        finally:
            os.unlink(path)


class TestCheckScope(unittest.TestCase):
    def test_no_scope_allows_everything(self):
        violations = check_scope(["a.py", "b/c.py"], scope=[])
        self.assertEqual(violations, [])

    def test_scope_matches_simple(self):
        violations = check_scope(["backend/api.py"], scope=["backend/"])
        self.assertEqual(violations, [])

    def test_scope_rejects_outside(self):
        violations = check_scope(["frontend/app.py"], scope=["backend/"])
        self.assertEqual(violations, ["frontend/app.py"])

    def test_forbidden_blocks_even_in_scope(self):
        violations = check_scope(
            ["backend/test_api.py"],
            scope=["backend/"],
            forbidden=["**/test_*.py"],
        )
        self.assertEqual(violations, ["backend/test_api.py"])

    def test_multiple_files_mixed(self):
        violations = check_scope(
            ["backend/api.py", "frontend/app.py", "tests/test_api.py"],
            scope=["backend/", "tests/"],
        )
        self.assertEqual(violations, ["frontend/app.py"])

    def test_glob_pattern_matches(self):
        violations = check_scope(
            ["src/foo.py", "src/sub/bar.py"],
            scope=["src/**"],
        )
        self.assertEqual(violations, [])


class TestEnforceScope(unittest.TestCase):
    def test_no_scope_no_op(self):
        with tempfile.TemporaryDirectory() as d:
            # Should not raise
            enforce_scope("step1", scope=None, cwd=d)

    def test_no_git_repo_skips_check(self):
        with tempfile.TemporaryDirectory() as d:
            # No .git directory — should warn/skip, not crash
            enforce_scope("step1", scope=["backend/"], cwd=d)


if __name__ == "__main__":
    unittest.main()
