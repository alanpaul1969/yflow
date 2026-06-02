"""
StdlibBackend — filesystem-backed memory store.

Layout: <root>/<slug-as-path>.md, e.g.:
    ~/.local/share/yflow/memory/infra/minimax-m3-config.md
    ~/.local/share/yflow/memory/projects/recognize/plan-status.md

Each file has YAML frontmatter + markdown body. See backend.py for the format.

No external dependencies beyond PyYAML (already required by yflow).
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from yflow.memory.backend import MemoryEntry


class StdlibBackend:
    """Filesystem-backed memory store. Default yflow memory backend."""

    def __init__(self, root: Path):
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def path(self, slug: str) -> Path:
        """Resolve slug to absolute path. Raises ValueError on unsafe slugs."""
        if not slug or ".." in slug.split("/") or slug.startswith("/"):
            raise ValueError(f"Invalid slug: {slug!r} (no '..' or leading '/')")
        return self.root / f"{slug}.md"

    def _parse(self, path: Path) -> MemoryEntry:
        raw = path.read_text(encoding="utf-8")
        fm, body = self._split_frontmatter(raw)
        slug = str(path.relative_to(self.root)).removesuffix(".md")

        # updated: prefer frontmatter, fallback to file mtime
        updated_str = fm.get("updated", "")
        try:
            updated = datetime.fromisoformat(updated_str) if updated_str else datetime.fromtimestamp(path.stat().st_mtime)
        except (ValueError, TypeError):
            updated = datetime.fromtimestamp(path.stat().st_mtime)

        return MemoryEntry(
            slug=slug,
            path=path,
            title=str(fm.get("title", slug.split("/")[-1])),
            type=str(fm.get("type", "note")),
            tags=list(fm.get("tags", []) or []),
            updated=updated,
            body=body,
            raw=raw,
        )

    @staticmethod
    def _split_frontmatter(raw: str) -> tuple[dict, str]:
        """Split raw markdown into (frontmatter_dict, body)."""
        if not raw.startswith("---"):
            return {}, raw
        # Find closing ---
        rest = raw[3:]
        end = rest.find("\n---")
        if end < 0:
            return {}, raw
        fm_text = rest[:end].strip()
        body = rest[end + 4 :].lstrip("\n")
        try:
            fm = yaml.safe_load(fm_text) or {}
            if not isinstance(fm, dict):
                fm = {}
        except yaml.YAMLError:
            fm = {}
        return fm, body

    def _dump(self, slug: str, body: str, *, title: str, type_: str, tags: list[str], updated: datetime) -> Path:
        fm = {
            "title": title,
            "type": type_,
            "tags": tags,
            "updated": updated.isoformat() if isinstance(updated, datetime) else str(updated),
        }
        fm_text = yaml.safe_dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False).rstrip()
        full = f"---\n{fm_text}\n---\n\n{body}\n"
        path = self.path(slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(full, encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # Public API (MemoryBackend protocol)
    # ------------------------------------------------------------------

    def add(
        self,
        slug: str,
        body: str | None = None,
        *,
        title: str | None = None,
        type: str = "note",
        tags: list[str] | None = None,
        from_file: Path | str | None = None,
    ) -> MemoryEntry:
        path = self.path(slug)
        if path.exists():
            raise FileExistsError(f"Memory entry already exists: {slug}")

        if from_file is not None:
            raw = Path(from_file).read_text(encoding="utf-8")
            # If file has its own frontmatter, use it as the source of truth
            fm, parsed_body = self._split_frontmatter(raw)
            if fm:
                # File already has frontmatter — use it
                title = title or str(fm.get("title", slug.split("/")[-1]))
                type = str(fm.get("type", type))
                tags = list(fm.get("tags", tags or []))
                body = parsed_body
            else:
                # No frontmatter — treat whole file as body
                body = raw
        body = body or ""
        title = title or slug.split("/")[-1]
        updated = datetime.now()
        self._dump(slug, body, title=title, type_=type, tags=tags or [], updated=updated)
        return self._parse(path)

    def get(self, slug: str) -> Optional[MemoryEntry]:
        path = self.path(slug)
        if not path.exists():
            return None
        return self._parse(path)

    def list(self, prefix: str | None = None, tag: str | None = None) -> list[MemoryEntry]:
        results = []
        for path in sorted(self.root.rglob("*.md")):
            if not path.is_file():
                continue
            try:
                entry = self._parse(path)
            except Exception:
                continue
            if prefix and not entry.slug.startswith(prefix):
                continue
            if tag and tag not in entry.tags:
                continue
            results.append(entry)
        return results

    def search(self, pattern: str) -> list[tuple[MemoryEntry, str]]:
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"Invalid regex: {e}")
        results = []
        for path in sorted(self.root.rglob("*.md")):
            if not path.is_file():
                continue
            try:
                raw = path.read_text(encoding="utf-8")
                entry = self._parse(path)
                for lineno, line in enumerate(raw.splitlines(), 1):
                    if regex.search(line):
                        results.append((entry, f"L{lineno}: {line.strip()[:120]}"))
                        break  # one match per file
            except Exception:
                continue
        return results

    def inject(self, slugs: list[str]) -> str:
        parts = []
        for slug in slugs:
            entry = self.get(slug)
            if entry is None:
                parts.append(f"# [missing: {slug}]\n\n_(not found in memory)_\n\n")
                continue
            parts.append(f"# === {slug} ===\n\n{entry.raw.rstrip()}\n\n")
        return "".join(parts)

    def rm(self, slug: str) -> bool:
        path = self.path(slug)
        if not path.exists():
            return False
        path.unlink()
        # Clean up empty parent dirs (but not root)
        parent = path.parent
        while parent != self.root and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
        return True

    def mv(self, old_slug: str, new_slug: str) -> MemoryEntry:
        old_path = self.path(old_slug)
        new_path = self.path(new_slug)
        if not old_path.exists():
            raise FileNotFoundError(f"Not found: {old_slug}")
        if new_path.exists():
            raise FileExistsError(f"Already exists: {new_slug}")
        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_path), str(new_path))
        # Clean up empty parent dirs
        parent = old_path.parent
        while parent != self.root and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
        return self._parse(new_path)
