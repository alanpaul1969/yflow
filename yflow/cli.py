"""
CLI for yflow — standalone workflow runner.

Usage:
  yamlflow run <file>      Execute a workflow
  yamlflow list            List all workflows
  yamlflow show <file>     Show execution plan
  yamlflow validate <file> Validate without running
  yamlflow create <name>   Create from template
  yamlflow stats           Show run analytics
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from yflow.engine import (
    build_workflow_prompt,
    classify_task,
    execute_workflow,
    get_available_templates,
    instantiate_template,
    list_workflows,
    load_template,
    load_workflow,
    resolve_execution_order,
    WORKFLOWS_DIR,
)


def main():
    parser = argparse.ArgumentParser(
        prog="yflow",
        description="YAML-defined multi-agent workflow orchestrator.",
    )
    subs = parser.add_subparsers(dest="command")

    # --- run ---
    run_p = subs.add_parser("run", help="Execute a workflow YAML file")
    run_p.add_argument("file", help="Path to workflow YAML file")
    run_p.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Print the generated prompt without executing",
    )
    run_p.add_argument(
        "--native", action="store_true",
        help="Use native execution (run command/reasonix/opencode steps locally)",
    )
    run_p.add_argument(
        "--exec", action="store_true",
        help="Pipe prompt to external agent (use YFLOW_EXEC env var for command)",
    )

    # --- list ---
    subs.add_parser("list", help="List all workflow YAML files")

    # --- stats ---
    subs.add_parser("stats", help="Show workflow run analytics")

    # --- show ---
    show_p = subs.add_parser("show", help="Show execution plan for a workflow")
    show_p.add_argument("file", help="Path to workflow YAML file")

    # --- validate ---
    val_p = subs.add_parser("validate", help="Validate a workflow YAML file")
    val_p.add_argument("file", help="Path to workflow YAML file")

    # --- create ---
    create_p = subs.add_parser("create", help="Create a new workflow from a template")
    create_p.add_argument("name", help="Workflow name (used as filename)")
    create_p.add_argument("--description", "-d", default="", help="Workflow description")
    create_p.add_argument("--from", "-f", dest="template", help="Template name (e.g. backend-bug-fix)")
    create_p.add_argument("--set", "-s", action="append", dest="vars", help="Set variable: key=value")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return _dispatch(args)


def _dispatch(args):
    handlers = {
        "run": _cmd_run,
        "list": _cmd_list,
        "stats": _cmd_stats,
        "show": _cmd_show,
        "validate": _cmd_validate,
        "create": _cmd_create,
    }
    return handlers.get(args.command, lambda _: _unknown(args.command))(args)


def _unknown(cmd):
    print(f"Unknown command: {cmd}")
    return 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_workflow_path(name: str) -> str:
    """Resolve a workflow name to a full path."""
    path = os.path.expanduser(name)
    if os.path.exists(path):
        return path

    wdir = Path(os.path.expanduser(WORKFLOWS_DIR))
    candidates = [
        wdir / name,
        wdir / f"{name}.yaml",
        wdir / f"{name}.yml",
    ]
    for c in candidates:
        if c.exists():
            return str(c)

    return path  # Return original so error shows what was tried


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _cmd_run(args) -> int:
    """Execute a workflow."""
    filepath = _resolve_workflow_path(args.file)

    if not os.path.exists(filepath):
        print(f"Error: file not found: {filepath}")
        return 1

    try:
        workflow = load_workflow(filepath)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    # --native mode
    if args.native:
        print(f"⚡ Native mode: executing locally...")
        result = execute_workflow(workflow)
        local_count = len(result["local_outputs"])
        deferred_count = len(result.get("deferred_steps", []))
        print(f"   Local steps: {local_count} completed")
        print(f"   Deferred steps: {deferred_count}")

        if result["prompt"]:
            print(f"\n--- Deferred steps prompt ---\n")
            print(result["prompt"])
            print(f"\n--- Feed this to your AI agent ---")
            return 0
        else:
            print("   ✅ All steps executed natively!")
            return 0

    # Standard prompt generation
    prompt = build_workflow_prompt(workflow)

    if args.dry_run:
        print("=" * 60)
        print(f"DRY RUN — Generated prompt for workflow: {workflow['name']}")
        print("=" * 60)
        print()
        print(prompt)
        print()
        print("=" * 60)
        print("To execute, remove --dry-run flag.")
        return 0

    # --exec mode: pipe to external agent
    if args.exec:
        exec_cmd = os.environ.get("YFLOW_EXEC", "")
        if not exec_cmd:
            print("Error: --exec requires YFLOW_EXEC env var")
            print("Example: export YFLOW_EXEC='hermes -p'")
            return 1

        import subprocess

        print(f"🚀 Executing workflow: {workflow['name']}")
        print(f"   Steps: {len(workflow.get('steps', []))}")
        print(f"   Piping to: {exec_cmd}")
        print()

        try:
            subprocess.run(
                exec_cmd.split() + [prompt],
                text=True,
                timeout=600,
            )
            return 0
        except subprocess.TimeoutExpired:
            print("⏰ Workflow timed out after 10 minutes")
            return 1
        except FileNotFoundError:
            print(f"Error: command not found: {exec_cmd.split()[0]}")
            return 1

    # Default: print prompt
    print(f"Workflow: {workflow['name']}")
    print(f"Steps: {len(workflow.get('steps', []))}")
    print()
    print(prompt)
    print()
    print("---")
    print("Run with --native for local execution, or --exec to pipe to an AI agent.")
    return 0


def _cmd_list(args) -> int:
    """List all workflow files."""
    workflows = list_workflows()

    if not workflows:
        print(f"No workflows found in {WORKFLOWS_DIR}")
        print(f"\nCreate one with: yamlflow create <name>")
        return 0

    print(f"{'WORKFLOW':<30} {'STEPS':<8} {'FILE'}")
    print("-" * 70)
    for w in workflows:
        print(f"{w['name']:<30} {w['steps']:<8} {w['filename']}")

    print(f"\n{len(workflows)} workflow(s) found.")
    return 0


def _cmd_stats(args) -> int:
    """Show workflow run analytics."""
    history_file = os.path.join(
        os.path.dirname(WORKFLOWS_DIR), "workflows", ".run_history.jsonl"
    )

    if not os.path.exists(history_file):
        print("No workflow runs recorded yet.")
        print("Run a workflow to start tracking: yamlflow run <name> --native")
        return 0

    runs = []
    with open(history_file) as f:
        for line in f:
            try:
                runs.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue

    if not runs:
        print("No valid run records found.")
        return 0

    total = len(runs)
    successes = sum(1 for r in runs if r.get("success"))
    workflow_counts = Counter(r["workflow"] for r in runs)

    timestamps = [r["timestamp"] for r in runs if "timestamp" in r]
    first_ts = timestamps[0][:10] if timestamps else "?"
    last_ts = timestamps[-1][:10] if timestamps else "?"

    print(f"📊 Workflow Analytics")
    print(f"   {first_ts} → {last_ts}  |  {total} runs, "
          f"{successes} succeeded ({successes * 100 // total if total else 0}%)")
    print()
    print(f"{'Workflow':<30} {'Runs':<8} {'Success %'}")
    print("-" * 50)
    for wf, count in workflow_counts.most_common():
        wf_runs = [r for r in runs if r["workflow"] == wf]
        wf_ok = sum(1 for r in wf_runs if r.get("success"))
        pct = f"{wf_ok * 100 // count}%" if count else "0%"
        print(f"{wf:<30} {count:<8} {pct}")
    print()

    print("Recent runs:")
    for r in runs[-5:]:
        ts = r.get("timestamp", "?")[:19]
        wf = r.get("workflow", "?")
        ok = "✅" if r.get("success") else "⚠️"
        steps = f"local={r.get('local_steps', 0)} def={r.get('deferred_steps', 0)}"
        print(f"  {ts}  {ok}  {wf}  ({steps})")

    return 0


def _cmd_show(args) -> int:
    """Show execution plan for a workflow."""
    filepath = _resolve_workflow_path(args.file)

    if not os.path.exists(filepath):
        print(f"Error: file not found: {filepath}")
        return 1

    try:
        workflow = load_workflow(filepath)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    waves = resolve_execution_order(workflow.get("steps", []))

    print(f"Workflow: {workflow['name']}")
    if workflow.get("description"):
        print(f"  {workflow['description']}")
    print()

    for i, wave in enumerate(waves):
        parallel = "⚡ parallel" if len(wave) > 1 else ""
        print(f"Wave {i + 1} {parallel}:")
        for sid in wave:
            step = next((s for s in workflow["steps"] if s["id"] == sid), {})
            stype = step.get("type", "subagent")
            name = step.get("name", sid)
            deps = step.get("depends_on", [])
            if isinstance(deps, str):
                deps = [deps]
            dep_str = f" ← {' '.join(deps)}" if deps else ""
            print(f"  [{stype}] {sid}: {name}{dep_str}")
        print()

    print(f"Generated prompt ({len(build_workflow_prompt(workflow))} chars)")
    return 0


def _cmd_validate(args) -> int:
    """Validate a workflow YAML file."""
    filepath = _resolve_workflow_path(args.file)

    if not os.path.exists(filepath):
        print(f"Error: file not found: {filepath}")
        return 1

    try:
        workflow = load_workflow(filepath)
        print(f"✅ Valid: {workflow['name']}")
        print(f"   Steps: {len(workflow.get('steps', []))}")
        waves = resolve_execution_order(workflow.get("steps", []))
        print(f"   Waves: {len(waves)}")
        return 0
    except ValueError as e:
        print(f"❌ Invalid: {e}")
        return 1
    except Exception as e:
        print(f"❌ Parse error: {e}")
        return 1


def _cmd_create(args) -> int:
    """Create a new workflow from template."""
    name = args.name
    description = args.description or f"Workflow: {name}"

    safe_name = name.lower().replace(" ", "-").replace("/", "-")
    filename = f"{safe_name}.yaml"

    workflows_dir = Path(os.path.expanduser(WORKFLOWS_DIR))
    workflows_dir.mkdir(parents=True, exist_ok=True)

    filepath = workflows_dir / filename

    if filepath.exists():
        print(f"Error: {filepath} already exists")
        return 1

    # Parse --set variables
    vars_dict = {}
    if args.vars:
        for var_arg in args.vars:
            if "=" not in var_arg:
                print(f"Warning: skipping invalid variable '{var_arg}' (expected key=value)")
                continue
            k, v = var_arg.split("=", 1)
            vars_dict[k] = v

    if args.template:
        try:
            template_data = load_template(args.template)
        except FileNotFoundError as e:
            print(f"Error: {e}")
            return 1

        variables = dict(vars_dict)
        if "TASK_DESCRIPTION" not in variables:
            variables["TASK_DESCRIPTION"] = description

        generated = instantiate_template(template_data, variables)
        filepath.write_text(generated)

        print(f"✅ Created: {filepath} (from template '{args.template}')")
    else:
        default_template = f"""# {name}
name: "{name}"
description: "{description}"
version: "1.0"

# Optional: define variables used across steps
# variables:
#   repo_path: "~/project"

steps:
  # Step 1: Inspect (subagent)
  - id: inspect
    name: "Inspect codebase"
    type: subagent
    context: |
      Inspect the codebase at [path].
      Count files, LOC, languages, dependencies.
      Return a structured report.
    toolsets: [terminal, file]

  # Step 2: Review (skill)
  # - id: review
  #   name: "Code quality review"
  #   type: skill
  #   skill: code-review
  #   depends_on: inspect
  #   input:
  #     files: $inspect.output

  # Step 3: Command (native)
  # - id: test
  #   type: command
  #   command: "echo 'all done'"
  #   depends_on: review

# Tips:
# - type: subagent | skill | command | reasonix | opencode | workflow
# - depends_on: step_id or [step_id1, step_id2]
# - Steps without depends_on run in the first wave (can be parallel)
# - Use $variables.xxx to reference global variables
# - Use $step-id.output to reference a previous step's output
"""

        filepath.write_text(default_template)
        print(f"✅ Created: {filepath}")

    print(f"   Edit this file to define your workflow steps.")
    print(f"   Run with: yamlflow run {filepath}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
