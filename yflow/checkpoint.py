"""
yflow.checkpoint — Human-in-the-loop checkpoint for workflows.

Implements the 3-checkpoint pattern from BlockTempo's 7-agent factory:
engine pauses at a human_checkpoint step, notifies the user, and waits
for an approve/reject decision before continuing.

Behavior:
  - Interactive (TTY): prompts on stdin, blocks until user replies
  - Non-interactive (cron, webhook): writes .checkpoints/<id>.pending
    file, exits with code 75 (EX_TEMPFAIL). User can resume later
    with `yflow resume <workflow>` or by editing the pending file.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Exit code for "deferred awaiting human review" (sysexits.h-ish).
EX_DEFERRED = 75


class CheckpointDecision(Exception):
    """Raised when a checkpoint is rejected by the human reviewer."""

    def __init__(self, step_id: str, reason: str = ""):
        self.step_id = step_id
        self.reason = reason
        super().__init__(f"Checkpoint {step_id!r} rejected: {reason}")


def _pending_dir(cwd: str | os.PathLike = ".") -> Path:
    """Where pending checkpoint files live."""
    return Path(cwd) / ".checkpoints"


def _pending_path(step_id: str, cwd: str | os.PathLike = ".") -> Path:
    return _pending_dir(cwd) / f"{step_id}.pending"


def write_pending(
    step_id: str,
    message: str,
    workflow: str,
    cwd: str | os.PathLike = ".",
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Write a .checkpoints/<id>.pending file for async review.

    The file is JSON with: step_id, message, workflow, created_at, status.
    A separate `yflow checkpoint approve <id>` or `reject <id>` command
    (or manual file edit) can resume the workflow.
    """
    pending_dir = _pending_dir(cwd)
    pending_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "step_id": step_id,
        "message": message,
        "workflow": workflow,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "metadata": metadata or {},
    }
    p = _pending_path(step_id, cwd)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def read_pending(step_id: str, cwd: str | os.PathLike = ".") -> dict | None:
    """Read a pending checkpoint file. Returns None if absent."""
    p = _pending_path(step_id, cwd)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def resolve_pending(
    step_id: str,
    decision: str,
    cwd: str | os.PathLike = ".",
    reviewer: str = "",
    note: str = "",
) -> dict:
    """Mark a pending checkpoint as approved/rejected.

    Returns the updated payload. Raises FileNotFoundError if no pending file.
    """
    payload = read_pending(step_id, cwd)
    if payload is None:
        raise FileNotFoundError(f"No pending checkpoint {step_id!r}")
    payload["status"] = "approved" if decision == "approve" else "rejected"
    payload["decision_at"] = datetime.now(timezone.utc).isoformat()
    payload["reviewer"] = reviewer
    payload["note"] = note
    p = _pending_path(step_id, cwd)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def list_pending(cwd: str | os.PathLike = ".") -> list[dict]:
    """Return all pending checkpoints, newest first."""
    pdir = _pending_dir(cwd)
    if not pdir.exists():
        return []
    out: list[dict] = []
    for p in pdir.glob("*.pending"):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return out


def _is_tty() -> bool:
    """True if stdin is attached to a terminal."""
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def execute_checkpoint(
    step: dict,
    workflow_name: str,
    cwd: str | os.PathLike = ".",
) -> None:
    """Execute a human_checkpoint step.

    Args:
        step: The step dict (must have id, message).
        workflow_name: Identifier of the workflow (for the pending file).
        cwd: Working directory for the .checkpoints/ folder.

    Raises:
        CheckpointDecision: if the reviewer rejects.
        SystemExit(EX_DEFERRED=75): if no TTY and we wrote a pending file.

    In TTY mode, blocks on stdin. In non-TTY mode, writes pending file
    and exits so cron/webhook contexts can resume later.
    """
    step_id = step["id"]
    message = step.get("message", f"Review step {step_id}")
    metadata = {k: v for k, v in step.items() if k not in ("id", "type", "message")}

    if _is_tty():
        # Interactive: prompt on stdin
        print(f"\n{'=' * 70}")
        print(f"⏸  CHECKPOINT: {step_id}")
        print(f"{'=' * 70}")
        print(message)
        print(f"{'=' * 70}")
        while True:
            try:
                reply = input("Approve to continue, reject to abort [a/r]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n[checkpoint] Aborted by user (no input)")
                raise CheckpointDecision(step_id, "no input / EOF")
            if reply in ("a", "approve", "y", "yes"):
                return
            if reply in ("r", "reject", "n", "no"):
                reason = input("Reason (optional): ").strip()
                raise CheckpointDecision(step_id, reason)
            print("Please reply 'a' (approve) or 'r' (reject).")

    # Non-interactive: write pending file, exit
    pending_path = write_pending(
        step_id=step_id,
        message=message,
        workflow=workflow_name,
        cwd=cwd,
        metadata=metadata,
    )
    print(
        f"\n[checkpoint] Step {step_id!r} requires human review.\n"
        f"  Pending file: {pending_path}\n"
        f"  To resume:\n"
        f"    yflow checkpoint approve {step_id}\n"
        f"    yflow checkpoint reject {step_id}  --note 'why'\n"
        f"  Exiting with code {EX_DEFERRED} (deferred awaiting human)."
    )
    sys.exit(EX_DEFERRED)
