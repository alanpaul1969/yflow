"""
Tests for yflow memory — StdlibBackend and CLI handlers.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from yflow.memory.stdlib_backend import StdlibBackend
from yflow.memory.paths import default_memory_dir
from yflow.memory.backend import MemoryEntry


class TestStdlibBackend(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="yflow-mem-test-"))
        self.backend = StdlibBackend(root=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- add / get ---

    def test_add_and_get(self):
        entry = self.backend.add(
            "infra/foo",
            body="# Foo\n\nThis is foo.",
            title="Foo",
            type="infrastructure",
            tags=["test", "demo"],
        )
        self.assertEqual(entry.slug, "infra/foo")
        self.assertEqual(entry.title, "Foo")
        self.assertEqual(entry.type, "infrastructure")
        self.assertEqual(entry.tags, ["test", "demo"])
        self.assertIn("This is foo.", entry.body)

        got = self.backend.get("infra/foo")
        self.assertIsNotNone(got)
        assert got is not None  # for type checker
        self.assertEqual(got.title, "Foo")

    def test_nested_path_creation(self):
        self.backend.add("projects/recognize/plan-status", body="...")
        self.assertTrue((self.tmp / "projects" / "recognize" / "plan-status.md").exists())

    def test_add_duplicate_raises(self):
        self.backend.add("dup", body="...")
        with self.assertRaises(FileExistsError):
            self.backend.add("dup", body="...")

    def test_add_from_file(self):
        src = self.tmp.parent / "src_input.md"
        src.write_text("Body from file content.", encoding="utf-8")
        entry = self.backend.add("from/file", from_file=src)
        self.assertIn("Body from file content", entry.body)

    def test_add_unsafe_slug_rejected(self):
        with self.assertRaises(ValueError):
            self.backend.add("../etc/passwd", body="...")
        with self.assertRaises(ValueError):
            self.backend.add("/abs/path", body="...")

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.backend.get("nope"))

    # --- list ---

    def test_list_returns_all(self):
        self.backend.add("a", body="...")
        self.backend.add("b", body="...")
        self.assertEqual(len(self.backend.list()), 2)

    def test_list_with_prefix(self):
        self.backend.add("infra/foo", body="...")
        self.backend.add("infra/bar", body="...")
        self.backend.add("projects/x", body="...")
        entries = self.backend.list(prefix="infra/")
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(e.slug.startswith("infra/") for e in entries))

    def test_list_with_tag(self):
        self.backend.add("a", body="...", tags=["m3", "config"])
        self.backend.add("b", body="...", tags=["config"])
        self.backend.add("c", body="...", tags=["other"])
        entries = self.backend.list(tag="m3")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].slug, "a")

    # --- search ---

    def test_search_basic(self):
        self.backend.add("foo", body="Some unique keyword here.")
        self.backend.add("bar", body="Different content.")
        matches = self.backend.search("unique")
        self.assertEqual(len(matches), 1)
        slug, line = matches[0][0].slug, matches[0][1]
        self.assertEqual(slug, "foo")
        # Line number is non-deterministic (depends on frontmatter length), just check it's there
        self.assertRegex(line, r"^L\d+:")

    def test_search_case_insensitive(self):
        self.backend.add("foo", body="# MixedCase MARKER")
        self.assertEqual(len(self.backend.search("mixedcase")), 1)
        self.assertEqual(len(self.backend.search("MIXEDCASE")), 1)

    def test_search_invalid_regex(self):
        with self.assertRaises(ValueError):
            self.backend.search("[unclosed")

    # --- inject ---

    def test_inject_merges(self):
        self.backend.add("a", body="Content of A")
        self.backend.add("b", body="Content of B")
        out = self.backend.inject(["a", "b"])
        self.assertIn("Content of A", out)
        self.assertIn("Content of B", out)
        self.assertIn("=== a ===", out)
        self.assertIn("=== b ===", out)

    def test_inject_missing_marks(self):
        out = self.backend.inject(["nope"])
        self.assertIn("[missing: nope]", out)

    # --- rm ---

    def test_rm_existing(self):
        self.backend.add("foo", body="...")
        self.assertTrue(self.backend.rm("foo"))
        self.assertIsNone(self.backend.get("foo"))

    def test_rm_missing(self):
        self.assertFalse(self.backend.rm("nope"))

    def test_rm_cleans_empty_parents(self):
        self.backend.add("deep/nested/entry", body="...")
        self.backend.rm("deep/nested/entry")
        # Empty parent dirs should be cleaned up
        self.assertFalse((self.tmp / "deep").exists())

    # --- mv ---

    def test_mv_basic(self):
        self.backend.add("old/name", body="...")
        self.backend.mv("old/name", "new/name")
        self.assertIsNone(self.backend.get("old/name"))
        self.assertIsNotNone(self.backend.get("new/name"))

    def test_mv_to_existing_fails(self):
        self.backend.add("a", body="...")
        self.backend.add("b", body="...")
        with self.assertRaises(FileExistsError):
            self.backend.mv("a", "b")

    # --- frontmatter roundtrip ---

    def test_frontmatter_roundtrip(self):
        self.backend.add("x", body="body content", title="Title", type="reference", tags=["a", "b"])
        entry = self.backend.get("x")
        self.assertIsNotNone(entry)
        assert entry is not None  # for type checker
        self.assertEqual(entry.title, "Title")
        self.assertEqual(entry.type, "reference")
        self.assertEqual(entry.tags, ["a", "b"])
        # Body should not contain frontmatter
        self.assertNotIn("---", entry.body)
        self.assertNotIn("title:", entry.body)
        # Raw should contain frontmatter
        self.assertIn("---", entry.raw)
        self.assertIn("title:", entry.raw)

    def test_invalid_frontmatter_falls_back(self):
        path = self.tmp / "broken.md"
        path.write_text("---\n: invalid yaml :::\n---\n\nbody here\n", encoding="utf-8")
        entry = self.backend.get("broken")  # slug will be 'broken' (filename without .md)
        self.assertIsNotNone(entry)
        assert entry is not None  # for type checker
        # Should still parse the body even if frontmatter is broken
        self.assertIn("body here", entry.body)

    def test_no_frontmatter_file(self):
        path = self.tmp / "plain.md"
        path.write_text("Just plain markdown content.\n", encoding="utf-8")
        entry = self.backend.get("plain")
        self.assertIsNotNone(entry)
        assert entry is not None  # for type checker
        self.assertEqual(entry.type, "note")
        self.assertIn("Just plain markdown", entry.body)


class TestPaths(unittest.TestCase):
    def test_default_memory_dir(self):
        d = default_memory_dir()
        # Should end with yflow/memory
        self.assertTrue(str(d).endswith("yflow/memory"))


class TestRealWorldExample(unittest.TestCase):
    """Simulate adding the actual memory entries from this session's work."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="yflow-mem-real-"))
        self.backend = StdlibBackend(root=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_full_gbrain_style_entry(self):
        """Simulate adding an infra/minimax-m3-config style entry."""
        body = """---
title: MiniMax M3 model + Hermes routing config
type: infrastructure
tags: [minimax, m3, model, hermes, routing, config, token-plan, vlm]
---

# MiniMax M3 — Main Model Configuration

## Identity

- **Provider**: `minimax`
- **Default model**: `MiniMax-M3`
- **Subscription**: `$50/month Token Plan Max`
"""
        # Simulate the file coming in
        src = self.tmp / "src.md"
        src.write_text(body, encoding="utf-8")

        entry = self.backend.add("infra/minimax-m3-config", from_file=src)
        self.assertEqual(entry.title, "MiniMax M3 model + Hermes routing config")
        self.assertEqual(entry.type, "infrastructure")
        self.assertEqual(len(entry.tags), 8)

    def test_inject_multiple_for_llm_context(self):
        """Simulate the use case of injecting cold memory for an LLM step."""
        self.backend.add("infra/minimax-m3-config", body="# M3\nConfig details...", tags=["minimax"])
        self.backend.add("infra/pipeline-canonical-numbers", body="# Pipeline\nPuLID w=0.75...", tags=["pulid"])
        self.backend.add("workflows/my-feature", body="# Workflow\nSteps...", tags=["workflow"])

        context = self.backend.inject(["infra/minimax-m3-config", "infra/pipeline-canonical-numbers"])
        # Should be one merged string with all content
        self.assertIn("M3", context)
        self.assertIn("PuLID w=0.75", context)
        self.assertNotIn("Workflow", context)  # not requested
        # Should have section markers
        self.assertIn("=== infra/minimax-m3-config ===", context)
        self.assertIn("=== infra/pipeline-canonical-numbers ===", context)

    def test_add_preserves_unicode(self):
        """Chinese/special chars in tags and body work without escaping."""
        entry = self.backend.add(
            "測試/條目",
            body="包含中文的 body",
            title="測試條目",
            tags=["中醫", "丹道", "chinese-novel"],
        )
        got = self.backend.get("測試/條目")
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(got.tags, ["中醫", "丹道", "chinese-novel"])
        self.assertIn("包含中文", got.body)


if __name__ == "__main__":
    unittest.main()
