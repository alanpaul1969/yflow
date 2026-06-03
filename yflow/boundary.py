"""
yflow.boundary — Per-step boundary enforcement.

Inspired by BlockTempo 7-agent factory pattern: each step declares
which tools it can use (tools_allowlist) and which paths it can
write to (scope). The engine enforces these via prompt injection
(tools) and post-run git diff check (scope).

This is the yflow equivalent of Claude Code's per-agent tool boundary.
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from pathlib import Path
from typing import Iterable


# All tool names a yflow subagent could conceivably use. The boundary
# tool allowlist works by listing what IS allowed; everything else is
# implicitly forbidden (the prompt tells the agent this).
ALL_KNOWN_TOOLS = frozenset({
    "read", "write", "edit", "delete", "search_files", "glob",
    "shell", "shell_exec", "bash", "git", "gitnexus", "delegate",
    "delegate_task", "image_generate", "vision", "web", "browser",
    "memory", "skill", "kb_query", "rag",
})


class ScopeViolation(Exception):
    """Raised when a step modifies files outside its declared scope."""

    def __init__(self, step_id: str, violations: list[str], scope: list[str]):
        self.step_id = step_id
        self.violations = violations
        self.scope = scope
        super().__init__(
            f"Step {step_id!r} modified files outside scope {scope!r}: "
            f"{violations}"
        )


def build_tools_allowlist_text(allowed: Iterable[str]) -> str:
    """Generate the prompt fragment that constrains a subagent's tools.

    This is injected at the top of the agent's prompt when the step
    declares `tools: [...]`. The receiving agent is expected to honor
    the boundary (best-effort, since we can't actually disable tools
    in external subagent runtimes).
    """
    allowed = list(allowed)
    if not allowed:
        return ""
    forbidden = sorted(ALL_KNOWN_TOOLS - set(allowed))
    allowed_str = ", ".join(f"`{t}`" for t in allowed)
    forbidden_str = ", ".join(f"`{t}`" for t in forbidden)
    return (
        "\n## TOOL BOUNDARY (MANDATORY — DO NOT VIOLATE)\n"
        f"You may ONLY use these tools: {allowed_str}.\n"
        f"You MUST NOT use any of: {forbidden_str}.\n"
        "If you need a tool not in the allowlist, STOP and report back "
        "to the orchestrator. Do not improvise by shelling out or using "
        "a different tool name.\n"
    )


def load_rules_file(path: str, base_dir: str | os.PathLike = ".") -> str:
    """Load a project rules file (e.g. AGENTS.md) and return its contents.

    Resolves relative paths against base_dir. Returns "" if file doesn't
    exist (warning, not error — workflows can run without rules).
    """
    base = Path(base_dir)
    p = Path(path)
    if not p.is_absolute():
        p = base / p
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def detect_register(rules_text: str) -> str | None:
    """Detect register from a rules/design file (brand | product | None).

    Recognizes two common patterns:
      1. YAML frontmatter style: `register: brand`
      2. Markdown heading style: `## Register` followed by `brand` on next line
         (or in the same line via `## Register: brand`)

    Case-insensitive. Returns None if not found — caller treats None
    as 'no register detected' and falls back to neutral rules.

    Inspired by pbakaus/impeccable's brand-vs-product register pattern.
    """
    if not rules_text:
        return None
    # Look in the first 30 lines
    head_lines = rules_text.splitlines()[:30]
    head = "\n".join(head_lines)

    # Pattern 1: YAML frontmatter `register: brand|product`
    m = re.search(r"(?im)^\s*register:\s*(brand|product)\b", head)
    if m:
        return m.group(1).lower()

    # Pattern 2: Markdown heading ## Register (or # Register) with
    # value on next line, e.g.:
    #   ## Register
    #
    #   brand
    for i, line in enumerate(head_lines):
        if re.match(r"(?im)^\s*#{1,4}\s*register\b", line):
            # Look at the next non-empty line
            for j in range(i + 1, min(i + 4, len(head_lines))):
                val = head_lines[j].strip().lower()
                # Strip optional `# comment` after the value
                val_clean = re.sub(r"\s*#.*$", "", val).strip()
                if val_clean in ("brand", "product"):
                    return val_clean
                if val:  # non-empty, non-match → stop looking
                    break
            # Pattern 3: same-line `## Register: brand`
            inline = re.search(r"(?i)register[:\s]+(brand|product)\b", line)
            if inline:
                return inline.group(1).lower()

    return None


# Anti-pattern lists injected per register (v0.6.3, port from
# pbakaus/impeccable's brand.md / product.md). Kept short and
# project-agnostic — for the full 7-domain reference, see the
# design-systems skill / impeccable skill.

_REGISTER_BRAND_TELLS = """\

## Register: BRAND

Design IS the product (landing pages, marketing, brand surfaces).
Permission: Committed / Full palette / Drenched color strategies.
Risk tolerance: high. Distinctiveness over safety.

**Banned (match-and-refuse):**
- Cream/sand/parchment body backgrounds (the 2026 AI default)
- Hero-metric template (big number + small label + gradient accent)
- Identical card grids (icon + heading + text, repeated)
- Side-stripe borders (border-left/right colored > 1px)
- Glassmorphism as default (BackdropFilter used decoratively)
- Tiny uppercase tracked eyebrows above every section
- Numbered section markers (01 / 02 / 03) above every section
- Inter / Roboto / Geist / Fraunces / Space Grotesk fonts
- Em dashes in body copy
- "X theater" copy ("engagement theater", "productivity theater")
- Aphoristic cadence as default voice

**Allowed:**
- Single saturated color drench (terracotta, oxblood, deep ochre, near-black)
- Asymmetric compositions, varied spacing for rhythm
- Imagery-led hero (real project assets or Unsplash with verified URLs)
"""

_REGISTER_PRODUCT_TELLS = """\

## Register: PRODUCT

Design SERVES the product (app UI, admin, dashboard, tools).
Familiarity is a feature. Earned trust. The tool should disappear
into the task.

**Banned (match-and-refuse):**
- Decorative motion that doesn't convey state
- Display fonts in UI labels, buttons, data
- Reinvented standard affordances (custom scrollbars, weird form controls)
- Heavy color or full-saturation accents on inactive states
- Modal as first thought (exhaust inline / progressive alternatives first)
- Inconsistent component vocabulary across screens
- Cream/sand body backgrounds (still an AI tell even for products)
- Side-stripe borders on cards
- Ghost cards (1px border + heavy box-shadow)
- Over-rounding on cards (24px+)

**Allowed:**
- System fonts and familiar sans defaults (Inter, SF Pro, system-ui)
- Standard navigation (top bar + side nav, breadcrumbs, tabs, command palettes)
- Density: tables with many rows, panels with many labels
- Consistency over surprise
- 150-250 ms motion (state change, feedback, loading, reveal only)
"""


def build_rules_text(rules_path: str, base_dir: str | os.PathLike = ".") -> str:
    """Generate the prompt fragment that prepends project rules.

    Mirrors Claude Code's CLAUDE.md auto-injection: every step that
    declares `rules_file: ./AGENTS.md` gets the file contents prepended
    to its prompt as project context.

    v0.6.3: register-aware. If the rules file declares
    `register: brand|product`, appends the matching anti-pattern list
    so the agent always knows what NOT to do for this register.
    """
    body = load_rules_file(rules_path, base_dir)
    if not body:
        return ""
    register = detect_register(body)
    register_block = ""
    if register == "brand":
        register_block = _REGISTER_BRAND_TELLS
    elif register == "product":
        register_block = _REGISTER_PRODUCT_TELLS
    return (
        "\n## PROJECT RULES (from " + str(rules_path) + " — auto-injected)\n\n"
        + body
        + register_block
        + "\n## END PROJECT RULES\n"
    )


def _match_any(path: str, patterns: Iterable[str]) -> bool:
    """Return True if path matches any of the glob patterns.

    Patterns are matched as fnmatch globs against the full path. A
    trailing slash in a pattern means "directory" — foo/ matches foo
    and foo/anything, but not foobar.
    """
    for pat in patterns:
        # Normalize: strip trailing slash for fnmatch
        clean = pat.rstrip("/")
        if clean and fnmatch.fnmatch(path, clean):
            return True
        # Directory prefix match: foo/ means "anything under foo/"
        if pat.endswith("/") and (path == clean or path.startswith(clean + "/")):
            return True
    return False


def check_scope(
    modified_files: Iterable[str],
    scope: list[str],
    forbidden: list[str] | None = None,
) -> list[str]:
    """Return the list of files that violate scope/forbidden constraints.

    A file violates if:
      - `scope` is non-empty AND the file is NOT matched by any scope pattern
      - the file IS matched by any forbidden pattern

    Empty scope means "no restrictions" (backwards compat).
    """
    forbidden = forbidden or []
    violations: list[str] = []
    for f in modified_files:
        if scope and not _match_any(f, scope):
            violations.append(f)
            continue
        if forbidden and _match_any(f, forbidden):
            violations.append(f)
    return violations


def get_git_changed_files(
    cwd: str | os.PathLike = ".",
    baseline_ref: str | None = None,
) -> list[str]:
    """Return files modified since baseline_ref (or uncommitted if None).

    Returns [] if not a git repo. Always returns absolute paths.
    """
    cwd = Path(cwd)
    if not (cwd / ".git").exists():
        return []
    try:
        if baseline_ref:
            out = subprocess.run(
                ["git", "diff", "--name-only", baseline_ref, "--"],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
        else:
            # Uncommitted changes (staged + unstaged + untracked).
            # Use --untracked-files=all so files inside untracked dirs
            # appear individually.
            out = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            files = []
            for line in out.stdout.splitlines():
                # Format: XY filename (where XY is 2-char status)
                if len(line) < 4:
                    continue
                path = line[3:].strip()
                # Handle renames: "R  old -> new"
                if " -> " in path:
                    path = path.split(" -> ", 1)[1]
                files.append(path)
            return files
        return [f for f in out.stdout.splitlines() if f.strip()]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []


def enforce_scope(
    step_id: str,
    scope: list[str] | None,
    forbidden: list[str] | None = None,
    cwd: str | os.PathLike = ".",
    baseline_ref: str | None = None,
) -> None:
    """Raise ScopeViolation if the step's git diff is outside scope.

    No-op if scope is None/empty (backwards compat).
    """
    if not scope:
        return
    changed = get_git_changed_files(cwd=cwd, baseline_ref=baseline_ref)
    violations = check_scope(changed, scope, forbidden)
    if violations:
        raise ScopeViolation(step_id, violations, scope)
