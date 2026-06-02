"""
yflow memory — second-tier memory store (markdown files, XDG-compliant).

Zero dependencies beyond PyYAML (already a yflow dep).
Filesystem layout: ~/.local/share/yflow/memory/<slug>.md

Each file is markdown with YAML frontmatter:
    ---
    title: Some title
    type: note | reference | workflow | methodology | ...
    tags: [a, b, c]
    updated: 2026-06-03T10:30:00
    ---

    # Markdown body
"""

from yflow.memory.backend import MemoryBackend, MemoryEntry
from yflow.memory.paths import default_memory_dir
from yflow.memory.stdlib_backend import StdlibBackend

__all__ = [
    "MemoryBackend",
    "MemoryEntry",
    "StdlibBackend",
    "default_memory_dir",
]


def get_backend(root=None) -> StdlibBackend:
    """Factory: returns StdlibBackend (only backend for now)."""
    return StdlibBackend(root=root or default_memory_dir())
