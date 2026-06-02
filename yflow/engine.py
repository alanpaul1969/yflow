"""
YAML Workflow Engine — pure-Python multi-agent workflow orchestrator.

Translates declarative YAML workflow definitions into executable plans.
Supports subagent delegation, native command execution, variable passing,
sub-workflows, and template-based creation. One dependency: PyYAML.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# ---------------------------------------------------------------------------
# Paths (configurable via env or param)
# ---------------------------------------------------------------------------

def _default_workflows_dir() -> str:
    """Default workflows directory. Override with YAMLFLOW_HOME env var."""
    home = os.environ.get("YAMLFLOW_HOME", os.path.expanduser("~/.yamlflow"))
    return os.path.join(home, "workflows")


WORKFLOWS_DIR = _default_workflows_dir()
TEMPLATES_DIR = os.path.join(os.path.dirname(WORKFLOWS_DIR), "workflows", "_templates")


# ---------------------------------------------------------------------------
# YAML Schema
# ---------------------------------------------------------------------------

STEP_TYPES = {"subagent", "skill", "command", "reasonix", "opencode", "workflow", "gbrain", "kanban", "minimax"}


def validate_workflow(data: dict) -> List[str]:
    """Validate a workflow definition. Returns list of errors (empty = valid)."""
    errors = []

    if not isinstance(data, dict):
        return ["Workflow must be a YAML dictionary"]

    if "name" not in data:
        errors.append("Missing required field: 'name'")

    # Validate memory: section (v0.5.0)
    if "memory" in data:
        try:
            from yflow.memory_injection import validate_memory_section
            errors.extend(validate_memory_section(data["memory"]))
        except Exception as e:
            errors.append(f"memory section validation failed: {e}")

    if "steps" not in data or not isinstance(data["steps"], list):
        errors.append("Missing required field: 'steps' (must be a list)")
        return errors

    step_ids = set()
    for i, step in enumerate(data["steps"]):
        prefix = f"steps[{i}]"

        if not isinstance(step, dict):
            errors.append(f"{prefix}: must be a dictionary")
            continue

        if "id" not in step:
            errors.append(f"{prefix}: missing required field 'id'")
        else:
            sid = step["id"]
            if sid in step_ids:
                errors.append(f"{prefix}: duplicate step id '{sid}'")
            step_ids.add(sid)

        stype = step.get("type", "subagent")
        if stype not in STEP_TYPES:
            errors.append(
                f"{prefix}: unknown type '{stype}' "
                f"(must be one of: {', '.join(STEP_TYPES)})"
            )

        if stype == "subagent" and "context" not in step:
            errors.append(f"{prefix}: type=subagent requires 'context' field")

        if stype == "command" and "command" not in step:
            errors.append(f"{prefix}: type=command requires 'command' field")

        if stype == "kanban" and "goal" not in step:
            errors.append(f"{prefix}: type=kanban requires 'goal' field")

        if stype == "minimax" and not (step.get("prompt") or step.get("context")):
            errors.append(f"{prefix}: type=minimax requires 'prompt' or 'context' field")

        if stype == "gbrain" and "action" not in step:
            errors.append(f"{prefix}: type=gbrain requires 'action' field (query/search/put/get)")
        elif stype == "gbrain":
            action = step["action"]
            if action not in ("query", "search", "put", "get"):
                errors.append(f"{prefix}: unknown gbrain action '{action}', must be query/search/put/get")
            if action in ("query", "search") and "query" not in step:
                errors.append(f"{prefix}: gbrain {action} requires 'query' field")
            if action == "put" and ("slug" not in step or "content" not in step):
                errors.append(f"{prefix}: gbrain put requires 'slug' and 'content' fields")
            if action == "get" and "slug" not in step:
                errors.append(f"{prefix}: gbrain get requires 'slug' field")

    # Validate depends_on references
    for i, step in enumerate(data["steps"]):
        deps = step.get("depends_on", [])
        if isinstance(deps, str):
            deps = [deps]
        for dep in deps:
            if dep not in step_ids:
                errors.append(
                    f"steps[{i}].depends_on: referenced step '{dep}' not found"
                )

    return errors


# ---------------------------------------------------------------------------
# Variable resolution
# ---------------------------------------------------------------------------


def resolve_variables(
    template: str, variables: dict, step_outputs: dict = None
) -> str:
    """Resolve $variables.x and $step-id.output references in a string."""
    result = template

    # Resolve $variables.xxx
    if variables:
        for key, value in variables.items():
            result = result.replace(f"$variables.{key}", str(value))

    # Resolve $step-id.output
    if step_outputs:
        for step_id, output in step_outputs.items():
            result = result.replace(f"${step_id}.output", str(output))

    return result


# ---------------------------------------------------------------------------
# Native execution — WorkflowSession + step runners
# ---------------------------------------------------------------------------


class WorkflowSession:
    """Tracks step outputs during native workflow execution."""

    def __init__(self, variables: dict | None = None):
        self.outputs: dict[str, str] = {}
        self.vars: dict[str, str] = variables or {}

    def resolve(self, text: str) -> str:
        """Replace $variables.X and $step-id.output with actual values."""
        result = text
        for k, v in self.vars.items():
            result = result.replace(f"$variables.{k}", str(v))
        for step_id, output in self.outputs.items():
            result = result.replace(f"${step_id}.output", str(output))
        return result

    def capture(self, step_id: str, output: str) -> None:
        """Store step output (capped at 10KB to avoid context bloat)."""
        self.outputs[step_id] = output[:10000]


def execute_command_step(step: dict, session: WorkflowSession) -> str:
    """Run a command-type step locally and capture its output."""
    import subprocess as _sp

    cmd = session.resolve(step["command"])
    r = _sp.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
    output = (r.stdout or r.stderr)[:10000]
    session.capture(step["id"], output)
    return output


def execute_reasonix_step(step: dict, session: WorkflowSession) -> str:
    """Run a reasonix step locally and capture its output.

    Supports two modes:
      - run (default): Read-only analysis via `reasonix run` — 91%+ cache hit
      - acp: Code/write mode via `reasonix acp` — full filesystem + terminal tools

    For acp mode, uses ACP JSON-RPC over stdio to spawn a headless coding agent.
    Requires DEEPSEEK_API_KEY in environment.
    """
    import subprocess as _sp
    import json as _json

    prompt = session.resolve(step.get("prompt", step.get("context", "")))
    mode = step.get("mode", "run")
    model = step.get("model", "flash")
    workdir = session.resolve(step.get("workdir", os.getcwd()))
    timeout = step.get("timeout", 600 if mode == "acp" else 300)

    if mode == "acp":
        # ACP mode: full coding agent via reasonix acp
        # Build JSON-RPC payload for initialize + session/new + session/prompt
        init_req = _json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": True}
                },
                "clientInfo": {
                    "name": "yflow", "title": "yflow engine", "version": "0.1.0"
                }
            }
        })
        session_req = _json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "session/new",
            "params": {"cwd": workdir, "mcpServers": []}
        })
        prompt_req = _json.dumps({
            "jsonrpc": "2.0", "id": 3, "method": "session/prompt",
            "params": {
                "sessionId": "SESSION_ID_PLACEHOLDER",
                "prompt": [{"type": "text", "text": prompt}]
            }
        })

        # Use a Python one-liner to handle the ACP handshake
        acp_script = f'''
import sys, json, os
os.chdir({workdir!r})

# Read initialize response
init = json.loads(sys.stdin.readline())
if "error" in init:
    print("ACP init failed: " + str(init.get("error")), file=sys.stderr)
    sys.exit(1)

# Send session/new
print(json.dumps({{"jsonrpc":"2.0","id":2,"method":"session/new","params":{{"cwd":{workdir!r},"mcpServers":[]}}}}))
sys.stdout.flush()
sess = json.loads(sys.stdin.readline())
sid = sess.get("result",{{}}).get("sessionId","")
if not sid:
    print("ACP session/new failed: " + str(sess), file=sys.stderr)
    sys.exit(1)

# Send prompt
print(json.dumps({{"jsonrpc":"2.0","id":3,"method":"session/prompt","params":{{"sessionId":sid,"prompt":[{{"type":"text","text":{prompt!r}}}]}}}}))
sys.stdout.flush()

# Collect response chunks
text_parts = []
while True:
    try:
        line = sys.stdin.readline()
        if not line:
            break
        msg = json.loads(line)
        if msg.get("id") == 3:
            if "error" in msg:
                print("ACP error: " + str(msg["error"]), file=sys.stderr)
            break
        if msg.get("method") == "session/update":
            update = msg.get("params",{{}}).get("update",{{}})
            if update.get("sessionUpdate") == "agent_message_chunk":
                text = update.get("content",{{}}).get("text","")
                if text:
                    text_parts.append(text)
    except Exception:
        break

print("".join(text_parts))
'''
        r = _sp.run(
            ["python3", "-c", acp_script],
            input=_json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": 1,
                    "clientCapabilities": {"fs": {"readTextFile": True, "writeTextFile": True}},
                    "clientInfo": {"name": "yflow", "title": "yflow engine", "version": "0.1.0"}
                }
            }) + "\n",
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "HOME": os.path.expanduser("~")}
        )
        output = (r.stdout or r.stderr)[:20000]
    else:
        # Run mode: read-only, ultra-cheap (default)
        r = _sp.run(
            f'reasonix run "{prompt}" --model {model}',
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (r.stdout or r.stderr)[:20000]

    session.capture(step["id"], output)
    return output


def execute_reasonix_acp_step(step: dict, session: WorkflowSession) -> str:
    """Run a subagent step via Reasonix ACP (coding agent with auto escalation).

    Uses ``reasonix acp --yolo`` for headless coding agent mode.
    Default model is 'auto' (flash-first with <<<NEEDS_PRO>>> escalation).
    Effort defaults to 'high' (matching Claude Opus 4.8 convention).
    Set 'max' for critical tasks, 'medium' for quick fixes.

    Required: DEEPSEEK_API_KEY in environment. reasonix CLI installed.
    """
    import subprocess as _sp

    prompt = session.resolve(step.get("context", step.get("prompt", "")))
    model = step.get("model", "auto")
    workdir = session.resolve(step.get("workdir", step.get("dir", os.getcwd())))
    effort = step.get("effort", "high")  # default high (Opus 4.8 convention)
    timeout = step.get("timeout", 900)  # 15 min default for coding tasks

    r = _sp.run(
        ["reasonix", "acp", "--yolo",
         "--model", model,
         "--dir", workdir,
         "--effort", effort,
         prompt],
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "HOME": os.path.expanduser("~")},
    )
    output = (r.stdout or r.stderr)[:20000]
    session.capture(step["id"], output)
    return output


def execute_opencode_step(step: dict, session: WorkflowSession) -> str:
    """Run an opencode step locally and capture its output."""
    import subprocess as _sp

    prompt = session.resolve(step["prompt"])
    binary = os.path.expanduser("~/.opencode/bin/opencode")
    r = _sp.run(
        f'{binary} run "{prompt}" --model llama-local/qwen35b',
        shell=True,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = (r.stdout or r.stderr)[:20000]
    session.capture(step["id"], output)
    return output


def execute_subworkflow_step(
    step: dict, session: WorkflowSession, workflows_dir: str = None
) -> str:
    """Load and execute a referenced workflow YAML."""
    import json as _json

    wdir = Path(workflows_dir or WORKFLOWS_DIR)
    ref_name = step["workflow"]
    ref_path = wdir / f"{ref_name}.yaml"
    if not ref_path.exists():
        raise FileNotFoundError(f"Sub-workflow not found: {ref_path}")
    ref_workflow = load_workflow(str(ref_path))
    result = execute_workflow(ref_workflow)
    output = _json.dumps(result.get("local_outputs", {}), ensure_ascii=False)
    session.capture(step["id"], output)
    return output


def execute_gbrain_step(step: dict, session: WorkflowSession) -> str:
    """Run a gbrain step — query/search/put/get against the knowledge brain.

    Requires gbrain CLI available. Set GBRAIN_BIN env var to override path.
    Silently skips with warning if gbrain is not installed.
    """
    import shutil as _shutil
    import subprocess as _sp

    # Resolve gbrain binary
    gbrain_bin = os.environ.get("GBRAIN_BIN")
    if not gbrain_bin:
        gbrain_bin = _shutil.which("gbrain")
    if not gbrain_bin:
        # Fall back to local repo
        repo_cli = os.path.expanduser("~/gbrain/src/cli.ts")
        if os.path.exists(repo_cli):
            bun = _shutil.which("bun") or os.path.expanduser("~/.local/bin/bun")
            gbrain_bin = f"{bun} run {repo_cli}"

    if not gbrain_bin:
        msg = "[gbrain] gbrain CLI not found — install with: git clone https://github.com/garrytan/gbrain ~/gbrain && cd ~/gbrain && bun install"
        session.capture(step["id"], msg)
        return msg

    action = step["action"]
    sid = step["id"]
    limit = step.get("limit", 5)

    try:
        if action in ("query", "search"):
            query = session.resolve(step["query"])
            cmd = f'{gbrain_bin} {action} "{query}" --limit {limit}'
            source = step.get("source")
            if source:
                cmd += f" --source {source}"

        elif action == "put":
            slug = session.resolve(step["slug"])
            content = session.resolve(step["content"])
            cmd = f'{gbrain_bin} put "{slug}"'
            r = _sp.run(
                f'echo "{content}" | {cmd}',
                shell=True, capture_output=True, text=True, timeout=60,
            )
            output = r.stdout or r.stderr or f"put {slug}: ok"
            session.capture(sid, output[:10000])
            return output[:10000]

        elif action == "get":
            slug = session.resolve(step["slug"])
            cmd = f'{gbrain_bin} get "{slug}"'

        r = _sp.run(
            cmd, shell=True, capture_output=True, text=True, timeout=120,
        )
        output = r.stdout or r.stderr or f"{action} {step.get('query', step.get('slug', ''))}: no output"
        session.capture(sid, output[:20000])
        return output[:20000]

    except _sp.TimeoutExpired:
        msg = f"[gbrain] {action} timed out after 120s"
        session.capture(sid, msg)
        return msg
    except Exception as e:
        msg = f"[gbrain] {action} error: {e}"
        session.capture(sid, msg)
        return msg




def execute_minimax_step(step: dict, session: WorkflowSession) -> str:
    """Execute a `type: minimax` step — call MiniMax M3 directly via stdlib.

    Requires one of:
      - step["api_key"]
      - $YFLOW_MINIMAX_API_KEY env var
      - ~/.config/yflow/auth.json (key: minimax_api_key)

    YAML fields: see yflow.agents.minimax for full schema.
    """
    from yflow.agents.minimax import run as run_minimax
    return run_minimax(step, session)


def execute_kanban_step(step: dict, session: WorkflowSession) -> str:
    """Execute a kanban swarm step: decompose → parallel workers → verify → synthesize.

    Uses Hermes Kanban Swarm to auto-decompose complex tasks. Requires
    ``hermes`` CLI on PATH. Best for tasks where you don't know the
    decomposition ahead of time.

    YAML fields:
        goal: str (required) — the task goal
        workers: list[dict] — specialist profiles (default: 3 auto-assigned)
          - profile: str — kanban assignee (e.g. "debugger", "architect")
          - skills: list[str] — kanban skill names
          - effort: str — per-worker effort (low|medium|high|max, default: high)
        verifier: str — verifier assignee (default: "code-reviewer")
        synthesizer: str — synthesizer assignee (default: "architect")
        effort: str — default effort for all workers (low|medium|high|max, default: high)
        timeout: int — max seconds to wait (default: 600)
        verify: dict — verification gate (optional)
          gate: str — strict|normal|off (default: normal)
          checks: list[str] — extra checks (lint, test, self-review, type-check)
    """
    import shutil as _shutil
    import json as _json
    import subprocess as _sp
    import time as _time

    # Check hermes is available
    hermes_bin = os.environ.get("HERMES_BIN") or _shutil.which("hermes")
    if not hermes_bin:
        msg = "[kanban] hermes CLI not found — install Hermes Agent for kanban support"
        session.capture(step["id"], msg)
        return msg

    goal = session.resolve(step["goal"])
    workers_cfg = step.get("workers", [])
    verifier_assignee = step.get("verifier", "code-reviewer")
    synthesizer_assignee = step.get("synthesizer", "architect")
    timeout = step.get("timeout", 600)
    default_effort = step.get("effort", "high")
    verify_cfg = step.get("verify", {})
    verify_gate = verify_cfg.get("gate", "normal")
    verify_checks = verify_cfg.get("checks", [])

    # Build verify gate instructions
    verify_extra = ""
    if verify_gate == "strict":
        verify_extra = " STRICT GATE: "
        if verify_checks:
            verify_extra += f"Must run and pass: {', '.join(verify_checks)}. "
        verify_extra += "Reject if ANY check fails. Do not pass without evidence."
    elif verify_gate == "off":
        verify_extra = " [GATE OFF — auto-pass]"

    worker_args: list[str] = []
    if workers_cfg:
        for w in workers_cfg:
            profile = w.get("profile", "default")
            title = w.get("title", f"{profile} worker: {goal[:60]}")
            skills = ",".join(w.get("skills", []))
            worker_effort = w.get("effort", default_effort)
            # Embed effort hint in title for the worker to see
            if worker_effort != "high":
                title = f"[{worker_effort}] {title}"
            if skills:
                worker_args.extend(["--worker", f"{profile}:{title}:{skills}"])
            else:
                worker_args.extend(["--worker", f"{profile}:{title}"])
    else:
        worker_args.extend([
            "--worker", f"investigator:Investigate: {goal[:50]}",
            "--worker", f"fixer:Fix: {goal[:50]}",
            "--worker", f"tester:Test: {goal[:50]}",
        ])

    try:
        r = _sp.run(
            [hermes_bin, "kanban", "swarm",
             "--goal", goal + verify_extra,
             "--verifier", verifier_assignee,
             "--synthesizer", synthesizer_assignee,
             "--json"] + worker_args,
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "HOME": os.path.expanduser("~")},
        )
        if r.returncode != 0:
            raise RuntimeError(r.stderr or r.stdout)
    except Exception as e:
        msg = f"[kanban] swarm creation failed: {e}"
        session.capture(step["id"], msg)
        return msg

    try:
        swarm_info = _json.loads(r.stdout.strip())
    except _json.JSONDecodeError:
        swarm_info = {"raw": r.stdout.strip()}

    worker_ids = swarm_info.get("worker_ids", [])
    if isinstance(worker_ids, str):
        worker_ids = [worker_ids]
    root_id = swarm_info.get("root_id", "unknown")

    # Dispatch
    _sp.run(
        [hermes_bin, "kanban", "dispatch", "--once", "--max", str(len(worker_ids) + 2)],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "HOME": os.path.expanduser("~")},
    )

    # Poll
    start = _time.time()
    result = ""
    pending: list = []
    while _time.time() - start < timeout:
        r2 = _sp.run(
            [hermes_bin, "kanban", "list", "--json"],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "HOME": os.path.expanduser("~")},
        )
        try:
            tasks = _json.loads(r2.stdout) if r2.stdout.strip() else []
        except _json.JSONDecodeError:
            tasks = []

        if not isinstance(tasks, list):
            tasks = []

        swarm_tasks = [t for t in tasks if t.get("id") in (worker_ids + [root_id])]
        pending = [t for t in swarm_tasks if t.get("status") not in ("done", "archived")]

        if not pending:
            results = []
            for t in swarm_tasks:
                rid = t.get("result", "") or ""
                if rid:
                    results.append(f"[{t.get('id', '?')}] {rid[:500]}")
            result = "\n".join(results) if results else "Kanban swarm: all tasks completed"
            break

        _time.sleep(5)

    if not result:
        result = f"Kanban swarm: timed out after {timeout}s (pending: {len(pending)})"

    session.capture(step["id"], result)
    return result


# ---------------------------------------------------------------------------
# Dependency resolver
# ---------------------------------------------------------------------------


def resolve_execution_order(steps: List[dict]) -> List[List[str]]:
    """
    Resolve steps into execution waves. Each wave is a list of step IDs
    that can run in parallel. Waves are sequential.
    """
    step_map = {s["id"]: s for s in steps}
    remaining = set(step_map.keys())
    completed = set()
    waves = []

    while remaining:
        wave = []
        for sid in sorted(remaining):
            step = step_map[sid]
            deps = step.get("depends_on", [])
            if isinstance(deps, str):
                deps = [deps]

            if all(d in completed for d in deps):
                wave.append(sid)

        if not wave:
            # Circular dependency or isolated nodes
            break

        for sid in wave:
            remaining.remove(sid)
        waves.append(wave)
        completed.update(wave)

    return waves


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_workflow_prompt(workflow: dict) -> str:
    """
    Build a prompt from a workflow. Uses native execution for command/reasonix/
    opencode/workflow steps; defers subagent/skill steps for external execution.

    Returns a prompt string for an AI agent to execute remaining steps, or a
    summary string if all steps were executed natively.
    """
    try:
        result = execute_workflow(workflow)
        if result["prompt"]:
            return result["prompt"]
        # All steps executed natively — return summary
        outputs = result.get("local_outputs", {})
        summary = [f"Workflow '{workflow.get('name', '')}' completed natively."]
        for sid, out in outputs.items():
            summary.append(f"  {sid}: {len(out)} chars")
        return "\n".join(summary)
    except Exception:
        # Fall back to prompt-only mode for any failure
        pass

    # Fallback: pure prompt-based execution
    name = workflow.get("name", "Unnamed Workflow")
    description = workflow.get("description", "")
    steps = workflow.get("steps", [])
    variables = workflow.get("variables", {})

    waves = resolve_execution_order(steps)
    step_map = {s["id"]: s for s in steps}

    steps_text = []
    for wave_idx, wave in enumerate(waves):
        label = (
            f"Wave {wave_idx + 1} (parallel — {len(wave)} steps)"
            if len(wave) > 1
            else f"Step {wave_idx + 1}"
        )
        steps_text.append(f"\n### {label}")

        for sid in wave:
            step = step_map[sid]
            step_name = step.get("name", sid)
            stype = step.get("type", "subagent")
            steps_text.append(f"\n**{sid}**: {step_name} (type={stype})")

            deps = step.get("depends_on", [])
            if isinstance(deps, str):
                deps = [deps]
            if deps:
                steps_text.append(f"  ← depends on: {', '.join(deps)}")

            if stype in ("subagent", "reasonix", "opencode"):
                context = step.get("context", step.get("prompt", ""))
                context = resolve_variables(context, variables)
                toolsets = step.get("toolsets", ["terminal", "file", "web"])
                steps_text.append(f"  Use {stype} with toolsets={toolsets}:")
                for line in context.strip().split("\n"):
                    steps_text.append(f"    {line}")

            elif stype == "skill":
                skill_name = step.get("skill", "")
                steps_text.append(f"  Load skill: {skill_name}")

            elif stype == "command":
                cmd = resolve_variables(step.get("command", ""), variables)
                steps_text.append(f"  Command: `{cmd}`")

    vars_text = ""
    if variables:
        vars_text = "\n## Variables\n\n"
        for k, v in variables.items():
            vars_text += f"- `${k}` = `{v}`\n"

    return f"""Execute the following workflow, delegating each subagent step to an appropriate worker.

## Workflow: {name}

{description}

{vars_text}
## Execution Plan

{len(waves)} wave(s), {len(steps)} step(s).

{chr(10).join(steps_text)}

## Instructions

1. Load any skills before executing their steps
2. For subagent steps, use your delegation tool with exact context provided
3. Steps in same wave can run in parallel via batch delegation
4. Verify results after each wave before proceeding
5. Compile final summary after all steps complete
"""


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def load_template(name: str, templates_dir: str = None) -> dict:
    """Load a workflow template by name.

    Returns dict with 'content' (raw text) and 'data' (parsed YAML).
    """
    tdir = templates_dir or TEMPLATES_DIR
    path = os.path.join(tdir, f"{name}.yaml")

    if not os.path.exists(path):
        available = []
        if os.path.isdir(tdir):
            available = sorted(
                f.replace(".yaml", "") for f in os.listdir(tdir) if f.endswith(".yaml")
            )

        msg = f"Template '{name}' not found in {tdir}"
        if available:
            msg += f"\nAvailable templates: {', '.join(available)}"
        raise FileNotFoundError(msg)

    with open(path, "r") as f:
        raw_content = f.read()

    data = yaml.safe_load(raw_content)
    return {"content": raw_content, "data": data}


def get_available_templates(templates_dir: str = None) -> list[str]:
    """Return list of available template names."""
    tdir = templates_dir or TEMPLATES_DIR
    if not os.path.isdir(tdir):
        return []

    return sorted(
        f.replace(".yaml", "") for f in os.listdir(tdir) if f.endswith(".yaml")
    )


def instantiate_template(template_data: dict, variables: dict) -> str:
    """Replace all {KEY} placeholders in the template content with values."""
    content = template_data["content"]

    result = content
    for key, value in variables.items():
        placeholder = "{" + key + "}"
        result = result.replace(placeholder, str(value))

    return result


def classify_task(description: str) -> dict:
    """Keyword-based task classifier. Returns template name and suggested variables."""
    desc_lower = description.lower()

    flutter_bug_keywords = ("flutter", "bug", "fix", "crash")
    if all(kw in desc_lower for kw in ("flutter", "bug")) or (
        desc_lower.count("flutter") > 0
        and any(kw in desc_lower for kw in ("bug", "fix", "crash"))
    ):
        return {
            "template": "flutter-bug-fix",
            "variables": {"TASK_DESCRIPTION": description},
        }

    if desc_lower.count("flutter") > 0 and any(
        kw in desc_lower for kw in ("feature", "new", "add")
    ):
        return {
            "template": "flutter-feature",
            "variables": {"TASK_DESCRIPTION": description},
        }

    backend_keywords = ("api", "backend", "server")
    bug_fix_keywords = ("bug", "fix", "crash", "error", "broken", "break")
    feature_keywords = ("feature", "add")

    has_backend = any(kw in desc_lower for kw in backend_keywords)
    has_bug = any(kw in desc_lower for kw in bug_fix_keywords)
    has_feature = any(kw in desc_lower for kw in feature_keywords)

    if has_backend and has_bug:
        return {
            "template": "backend-bug-fix",
            "variables": {"TASK_DESCRIPTION": description},
        }

    if has_backend and has_feature:
        return {
            "template": "backend-feature",
            "variables": {"TASK_DESCRIPTION": description},
        }

    return {"template": None, "variables": {}}


# ---------------------------------------------------------------------------
# Workflow execution engine — native orchestration
# ---------------------------------------------------------------------------


def execute_workflow(workflow: dict, workflows_dir: str = None) -> dict:
    """Execute a workflow natively.

    Runs command/reasonix/opencode/workflow/gbrain steps locally.
    Subagent steps default to reasonix ACP (coding agent); use
    ``provider: hermes`` to defer them for external execution instead.
    Skill steps are always deferred.

    Returns:
        {"local_outputs": {step_id: output},
         "deferred_steps": [...],
         "prompt": str}
    """
    steps = workflow.get("steps", [])
    variables = workflow.get("variables", {})
    workflow_memory = workflow.get("memory", {}) or {}
    workflow_cold_load = workflow_memory.get("cold_load", []) if isinstance(workflow_memory, dict) else []
    if workflow_memory.get("budget_chars"):
        try:
            from yflow.memory_injection import check_budget
            total, ok = check_budget(workflow_cold_load, workflow_memory["budget_chars"])
            if not ok:
                print(f"[yflow] ⚠️  memory.cold_load budget exceeded: {total} > {workflow_memory['budget_chars']} chars (consider trimming)")
        except Exception as e:
            print(f"[yflow] ⚠️  memory budget check failed: {e}")

    session = WorkflowSession(variables)
    waves = resolve_execution_order(steps)
    # Shallow-copy each step dict so engine state (_cold_load, _resolved_*)
    # doesn't leak back into the caller's workflow. Fixes cross-run
    # idempotency issue reported in code review.
    step_map = {s["id"]: dict(s) for s in steps}
    wdir = workflows_dir or WORKFLOWS_DIR

    deferred_steps = []

    for wave in waves:
        for sid in wave:
            step = step_map[sid]
            stype = step.get("type", "subagent")

            # Inject cold memory slugs into step context (v0.5.0)
            if workflow_cold_load:
                step["_cold_load"] = workflow_cold_load

            # Resolve context/command/prompt with current session state
            if "context" in step:
                step["_resolved_context"] = session.resolve(step["context"])
            if "command" in step:
                step["_resolved_command"] = session.resolve(step["command"])
            if "prompt" in step:
                step["_resolved_prompt"] = session.resolve(step["prompt"])

            if stype == "command":
                execute_command_step(step, session)
            elif stype == "reasonix":
                execute_reasonix_step(step, session)
            elif stype == "opencode":
                execute_opencode_step(step, session)
            elif stype == "workflow":
                execute_subworkflow_step(step, session, workflows_dir=wdir)
            elif stype == "gbrain":
                execute_gbrain_step(step, session)
            elif stype == "kanban":
                execute_kanban_step(step, session)
            elif stype == "minimax":
                execute_minimax_step(step, session)
            elif stype == "subagent":
                # Default to reasonix ACP.  Hermes provider stays deferred for
                # backward compatibility with existing delegate_task callers.
                if step.get("provider", "reasonix") == "hermes":
                    deferred_steps.append(step)
                else:
                    execute_reasonix_acp_step(step, session)
            else:
                # skill — defer to external executor
                deferred_steps.append(step)

    # Build prompt for deferred steps
    prompt = ""
    if deferred_steps:
        prompt = build_deferred_prompt(workflow, deferred_steps, session)

    return {
        "local_outputs": session.outputs,
        "deferred_steps": deferred_steps,
        "prompt": prompt,
    }


def build_deferred_prompt(
    workflow: dict, deferred_steps: list, session: WorkflowSession
) -> str:
    """Build a prompt for deferred subagent/skill steps with outputs injected."""
    name = workflow.get("name", "Unnamed Workflow")
    description = workflow.get("description", "")

    # Inject cold memory (v0.5.0)
    cold_section = ""
    workflow_memory = workflow.get("memory", {}) or {}
    cold_load = workflow_memory.get("cold_load", []) if isinstance(workflow_memory, dict) else []
    if cold_load:
        try:
            from yflow.memory_injection import build_cold_context
            cold_section = build_cold_context(cold_load) + "\n"
        except Exception as e:
            cold_section = f"# ⚠️ memory load failed: {e}\n\n"

    parts = [
        cold_section,
        f"Execute the remaining steps for workflow: **{name}**",
        f"_{description}_" if description else "",
        "",
        "## Already completed (outputs available)",
    ]
    for sid, output in session.outputs.items():
        preview = output[:200].replace("\n", " ")
        parts.append(f"- `${sid}`: {preview}...")

    parts.extend(["", "## Remaining steps", ""])

    for i, step in enumerate(deferred_steps):
        sid = step["id"]
        stype = step.get("type", "subagent")
        name_s = step.get("name", sid)
        parts.append(f"### {i + 1}. {name_s} (`{sid}`, type={stype})")

        if stype == "subagent":
            ctx = step.get("_resolved_context", step.get("context", ""))
            toolsets = step.get("toolsets", ["terminal", "file"])
            parts.append(f"Delegate with toolsets={toolsets}:")
            parts.append(f"```\n{ctx}\n```")
        elif stype == "skill":
            skill_name = step.get("skill", "")
            parts.append(
                f"Load skill: `{skill_name}` and execute with "
                f"input: {step.get('input', {})}"
            )

        parts.append("")

    parts.append("Execute these steps in order using your delegation tool.")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------


def load_workflow(path: str) -> dict:
    """Load and parse a workflow YAML file."""
    with open(os.path.expanduser(path), "r") as f:
        data = yaml.safe_load(f)

    errors = validate_workflow(data)
    if errors:
        raise ValueError(f"Invalid workflow:\n" + "\n".join(f"  - {e}" for e in errors))

    return data


def list_workflows(workflows_dir: str = None) -> List[dict]:
    """List all workflow YAML files in the workflows directory."""
    wdir = Path(os.path.expanduser(workflows_dir or WORKFLOWS_DIR))
    if not wdir.exists():
        return []

    workflows = []
    for f in sorted(wdir.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text())
            steps_count = len(data.get("steps", []))
            workflows.append(
                {
                    "name": data.get("name", f.stem),
                    "description": data.get("description", ""),
                    "file": str(f),
                    "filename": f.name,
                    "steps": steps_count,
                }
            )
        except Exception:
            workflows.append(
                {
                    "name": f.stem,
                    "description": "(parse error)",
                    "file": str(f),
                    "filename": f.name,
                    "steps": 0,
                }
            )

    return workflows


def record_run(
    workflow_name: str,
    success: bool,
    local_steps: int = 0,
    deferred_steps: int = 0,
    error: str = "",
    history_file: str = None,
) -> None:
    """Record a workflow run to history for analytics."""
    import json
    from datetime import datetime, timezone

    hist = history_file or os.path.join(
        os.path.dirname(WORKFLOWS_DIR), "workflows", ".run_history.jsonl"
    )
    os.makedirs(os.path.dirname(hist), exist_ok=True)

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "workflow": workflow_name,
        "success": success,
        "local_steps": local_steps,
        "deferred_steps": deferred_steps,
        "error": error,
    }
    with open(hist, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
