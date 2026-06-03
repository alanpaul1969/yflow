"""
yflow.factory — `yflow factory init` CLI subcommand.

Scaffolds a 7-agent factory project from the reference template:
  - workflows/<name>.yaml
  - PRODUCT.md          (v0.6.3 — register declaration)
  - DESIGN.md           (v0.6.3 — color strategy, typography, banned tells)
  - AGENTS.md           (project rules — auto-injected via rules_file)
  - .checkpoints/

Usage:
  yflow factory init <name>            # scaffold in current dir
  yflow factory init <name> --out DIR  # scaffold into DIR
"""

from __future__ import annotations

import shutil
from pathlib import Path

# Path to the reference template shipped with the package.
TEMPLATE_PATH = Path(__file__).parent / "_templates" / "7-agent-factory.yaml"

AGENTS_MD_TEMPLATE = """\
# Project Rules (auto-injected into every yflow step via rules_file)

## Code style
- Python 3.9+; type hints on all new functions
- Tests in tests/; run with `pytest -x --tb=short -q`
- Never commit hardcoded secrets — use env vars or auth.json

## Architecture
- Backend code lives in backend/, services/, or api/
- Frontend code lives in frontend/, web/, mobile/, or lib/ui/
- Tests live in tests/ — only the verifier step may modify them
- Documentation lives in docs/ — humans edit by hand

## Boundaries (factory pattern)
- Each agent has a tool allowlist declared in its step. Read it.
- Each agent has a write scope declared in its step. Respect it.
- The implementation_validator step is read-only — it audits, never edits.
- human_checkpoint steps require explicit human approval to continue.
"""


# Default PRODUCT.md — register=product (most factory projects are tools).
# Override by editing the file after scaffold.
PRODUCT_MD_TEMPLATE = """\
# Product

## Register

product

## Users

[Describe who uses this product. Be specific — role, technical level,
what they were doing before this product existed.]

## Product Purpose

[One paragraph: what the product does, who it serves, how success
is measured. The "register" field above tells yflow which anti-pattern
list to inject into agent prompts — keep it aligned with PRODUCT.md
or DESIGN.md.]

## Brand Personality

[Two- or three-word personality (e.g. "calm, clinical, careful").
Voice traits: direct vs hedged, technical vs plain, specific vs
comprehensive. See pbakaus/impeccable for reference.]

## Anti-references

[What this product must NOT look like. For product register: avoid
the saturated AI SaaS tells — ghost cards, cream backgrounds,
over-rounding, decorative motion, "X theater" copy.]
"""


# Default DESIGN.md — minimal. v0.6.3 register-aware rules injection
# reads the `register:` field from this file (or PRODUCT.md) to know
# which anti-pattern list to append to every step's prompt.
DESIGN_MD_TEMPLATE = """\
# Design

## Register

product   # ← yflow reads this. brand|product|none

## Color Strategy

Restrained (one accent ≤ 10%). Tint neutrals with 0.005–0.015 chroma
toward brand hue. Use OKLCH.

## Typography

- One family is often right (Inter / SF Pro / system-ui for product).
- Fixed rem scale, not fluid (1.125–1.2 between steps).
- Line length 65–75ch for prose; tables can run denser.

## Layout

- Flexbox for 1D, Grid for 2D. Auto-fit grids: `repeat(auto-fit, minmax(280px, 1fr))`.
- Semantic z-index scale. Never 9999.
- Cards only when truly the best affordance. Nested cards are always wrong.

## Motion

- 150–250 ms. State change, feedback, loading, reveal. Nothing else.
- `@media (prefers-reduced-motion: reduce)` non-optional.
- No orchestrated page-load sequences.

## Absolute Bans

[See the `design` check in implementation_validator for the
machine-checkable list. Per-register tells are auto-injected into
every step's prompt via rules_file + register detection.]

- Ghost cards (border + heavy shadow)
- Over-rounding (24px+ on cards)
- Side-stripe borders
- Gradient text (`ShaderMask` on Text)
- Glassmorphism as default (`BackdropFilter` used decoratively)
- Cream/sand body backgrounds
"""


def init_factory(name: str, out_dir: str | Path = ".") -> dict:
    """Scaffold a new factory project.

    Returns a dict of created paths for the CLI to report.
    """
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    workflow_path = out_dir / "workflows" / f"{name}.yaml"
    agents_path = out_dir / "AGENTS.md"
    product_path = out_dir / "PRODUCT.md"
    design_path = out_dir / "DESIGN.md"
    checkpoints_path = out_dir / ".checkpoints"

    # Workflow file (from template, customized with project name)
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    # First line of template is "# =====... 7-Agent Software Factory... ====="
    # We replace the description line to mention the project name
    customized = template.replace(
        "name: \"7-Agent Software Factory\"",
        f"name: \"{name} (7-Agent Factory)\"",
    ).replace(
        "BlockTempo reference: 7 specialized agents + 3 human checkpoints",
        f"7-agent factory for project: {name}",
    )
    workflow_path.write_text(customized, encoding="utf-8")

    # AGENTS.md (only if it doesn't exist — don't clobber user content)
    if not agents_path.exists():
        agents_path.write_text(AGENTS_MD_TEMPLATE, encoding="utf-8")

    # PRODUCT.md (only if it doesn't exist)
    if not product_path.exists():
        product_path.write_text(PRODUCT_MD_TEMPLATE, encoding="utf-8")

    # DESIGN.md (only if it doesn't exist)
    if not design_path.exists():
        design_path.write_text(DESIGN_MD_TEMPLATE, encoding="utf-8")

    # .checkpoints/ (gitkeep-style empty dir)
    checkpoints_path.mkdir(parents=True, exist_ok=True)
    (checkpoints_path / ".gitkeep").touch()

    return {
        "workflow": workflow_path,
        "agents": agents_path,
        "product": product_path,
        "design": design_path,
        "checkpoints_dir": checkpoints_path,
    }
