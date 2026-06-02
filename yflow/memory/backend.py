"""
Abstract memory backend interface for yflow.

The Protocol below defines the contract. StdlibBackend is the default impl.
Future backends (e.g., GBrain) implement the same interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class MemoryEntry:
    """A single memory entry — a markdown file with frontmatter."""

    slug: str  # e.g. "infra/minimax-m3-config" (no .md extension)
    path: Path
    title: str
    type: str
    tags: list[str] = field(default_factory=list)
    updated: datetime = field(default_factory=datetime.now)
    body: str = ""  # markdown body (no frontmatter)
    raw: str = ""  # full file content (frontmatter + body)

    @property
    def size_chars(self) -> int:
        return len(self.raw)

    @property
    def size_lines(self) -> int:
        return self.raw.count("\n") + 1


@runtime_checkable
class MemoryBackend(Protocol):
    """Protocol for memory backends. Implementations: StdlibBackend, future GBrainBackend."""

    def add(
        self,
        slug: str,
        body: str | None = None,
        *,
        title: str | None = None,
        type: str = "note",
        tags: list[str] | None = None,
        from_file: Path | str | None = None,
    ) -> MemoryEntry: ...

    def get(self, slug: str) -> MemoryEntry | None: ...

    def list(self, prefix: str | None = None, tag: str | None = None) -> list[MemoryEntry]: ...

    def search(self, pattern: str) -> list[tuple[MemoryEntry, str]]:
        """Return list of (entry, matched_line) tuples."""
        ...

    def inject(self, slugs: list[str]) -> str:
        """Merge multiple entries into a single string for LLM context."""
        ...

    def rm(self, slug: str) -> bool: ...

    def mv(self, old_slug: str, new_slug: str) -> MemoryEntry: ...

    def path(self, slug: str) -> Path: ...
