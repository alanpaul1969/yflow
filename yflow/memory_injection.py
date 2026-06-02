"""
Memory injection — prepending cold-storage memory to step contexts.

When a workflow has:
    memory:
      cold_load:
        - infra/minimax-m3-config
        - infra/pipeline-canonical-numbers

…each step's prompt gets these entries prepended, so the LLM has the
"context" without re-querying each time.

Pure stdlib. Zero new dependencies.
"""

from __future__ import annotations

from typing import Any

from yflow.memory import StdlibBackend, default_memory_dir


def build_cold_context(slugs: list[str], root: Any = None) -> str:
    """Resolve a list of slugs to a single merged context string.

    Format:
        # === Cold memory (auto-injected) ===

        # === <slug-1> ===
        <raw content of slug-1>

        # === <slug-2> ===
        <raw content of slug-2>

    If a slug doesn't exist, emits a clear `[missing]` marker so the LLM
    notices (instead of silently dropping).
    """
    if not slugs:
        return ""
    backend = StdlibBackend(root=root or default_memory_dir())
    parts = ["# === Cold memory (auto-injected from yflow memory) ===\n"]
    for slug in slugs:
        entry = backend.get(slug)
        if entry is None:
            parts.append(f"# === {slug} ===\n\n[missing: {slug} not found in memory]\n\n")
            continue
        parts.append(f"# === {slug} ===\n\n{entry.raw.rstrip()}\n\n")
    return "".join(parts)


def validate_memory_section(memory: dict) -> list[str]:
    """Validate a workflow's `memory:` section. Returns list of errors."""
    errors: list[str] = []
    if not isinstance(memory, dict):
        return [f"'memory' must be a dict, got {type(memory).__name__}"]

    if "cold_load" in memory:
        if not isinstance(memory["cold_load"], list):
            errors.append("memory.cold_load must be a list of slugs")
        else:
            for slug in memory["cold_load"]:
                if not isinstance(slug, str) or not slug.strip():
                    errors.append(f"memory.cold_load: invalid slug {slug!r}")

    if "budget_chars" in memory:
        bc = memory["budget_chars"]
        if not isinstance(bc, int) or bc < 0:
            errors.append(f"memory.budget_chars must be a non-negative int, got {bc!r}")

    if "markers" in memory:
        if not isinstance(memory["markers"], list):
            errors.append("memory.markers must be a list of strings")
        else:
            for m in memory["markers"]:
                if not isinstance(m, str):
                    errors.append(f"memory.markers: invalid marker {m!r}")

    return errors


def check_budget(slugs: list[str], budget: int, root: Any = None) -> tuple[int, bool]:
    """Sum the chars of all slugs. Return (total, within_budget)."""
    if not slugs:
        return 0, True
    backend = StdlibBackend(root=root or default_memory_dir())
    total = 0
    for slug in slugs:
        entry = backend.get(slug)
        if entry is not None:
            total += entry.size_chars
    return total, total <= budget
