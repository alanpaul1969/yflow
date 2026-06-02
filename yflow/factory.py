"""
yflow.factory — `yflow factory init` CLI subcommand.

Scaffolds a 7-agent factory project from the reference template:
  - workflows/<name>.yaml
  - AGENTS.md
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


def init_factory(name: str, out_dir: str | Path = ".") -> dict:
    """Scaffold a new factory project.

    Returns a dict of created paths for the CLI to report.
    """
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    workflow_path = out_dir / "workflows" / f"{name}.yaml"
    agents_path = out_dir / "AGENTS.md"
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

    # .checkpoints/ (gitkeep-style empty dir)
    checkpoints_path.mkdir(parents=True, exist_ok=True)
    (checkpoints_path / ".gitkeep").touch()

    return {
        "workflow": workflow_path,
        "agents": agents_path,
        "checkpoints_dir": checkpoints_path,
    }
