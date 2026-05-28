# yflow

> **The Makefile for AI workflows** — 1 dependency, zero daemons, provider-agnostic.

Define multi-agent workflows in YAML. Run them anywhere. No Docker, no servers, no lock-in.

## Why yflow?

AI agent platforms are powerful but heavyweight — dozens of dependencies, daemons, Docker, and vendor lock-in. yflow is different:

| Feature | yflow | Claude Code Workflow | awf | AutoTeam | Animus | AQM |
|---------|-------|----------------------|-----|----------|--------|-----|
| Dependencies | 1 (PyYAML) | Node.js + Anthropic API | 20+ | 30+ | 15+ | 25+ |
| Daemon required | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Docker required | ❌ | ❌ | ✅ | ✅ | ❌ | ✅ |
| Provider-agnostic | ✅ | ❌ (Anthropic-only) | ✅ | ❌ | ✅ | ❌ |
| Definition format | YAML (~20 lines) | Generated code (300+ lines) | YAML | Python DSL | YAML | YAML |
| Variable passing | ✅ `$step-id.output` | ❌ | ✅ | ❌ | ❌ | ❌ |
| Sub-workflows | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Template system | ✅ auto-classify | ❌ | ❌ | ❌ | ❌ | ❌ |
| Persistence | Permanent | 3-day auto-delete | Permanent | Permanent | Permanent | Permanent |

### yflow vs Claude Code Workflow

Claude Code added a Workflow feature in v2.1.47 (`/workflow`, `--ultraworkflow`) — a major step forward for multi-agent orchestration. But it's a different design philosophy:

**Definition format:** Claude Code generates 300+ line code scripts. yflow uses declarative YAML (~20 lines). Same power, less ceremony.

**Vendor lock-in:** Claude Code Workflow requires Node.js + an Anthropic API key. yflow is pure Python with one dependency (PyYAML). Use any LLM provider.

**Persistence:** Claude Code Workflow scripts auto-delete after 3 days (unless manually saved to `~/.claude/workflows/`). yflow workflows are permanent files you control.

**Complementary, not competing.** Claude Code Workflow excels at Anthropic-native, single-session coding pipelines. yflow excels at cross-provider, persistent, multi-tool orchestration. Use yflow to define the pipeline, and Claude Code (or any agent) as one of the executors.

## Install

```bash
pip install yflow
```

That's it. No Docker, no daemon, no API keys. Just `yflow` on your PATH.

## yflow init — Interactive Setup

```bash
yflow init
```

Launches a 4-question wizard:

| Question | Options | Default |
|----------|---------|---------|
| Subagent provider | hermes, claude-code, opencode, reasonix | `reasonix` |
| Default model | deepseek-v4-flash, deepseek-v4-pro, local | `deepseek-v4-flash` |
| GitHub token | (optional) | — |
| Workflows directory | any path | `~/.config/yflow/workflows` |

Creates:

- `~/.config/yflow/config.yaml` — your defaults (provider, model, paths)
- `~/.config/yflow/workflows/hello-world.yaml` — an example workflow to get started

Re-run any time to change your configuration.

## Quick Start

### 1. Create a workflow

```bash
yflow create hello-world
```

### 2. Edit it

```yaml
name: "Hello World"
description: "My first yflow pipeline"

steps:
  - id: greet
    name: "Say hello"
    type: command
    command: "echo 'Hello from yflow!'"

  - id: verify
    name: "Verify output"
    type: command
    command: "echo 'Previous step said: $greet.output'"
    depends_on: greet
```

### 3. Run it

```bash
yflow run hello-world --native
```

```
⚡ Native mode: executing locally...
   Local steps: 2 completed
   ✅ All steps executed natively!
```

## Step Types

| Type | Description | Default provider |
|------|-------------|------------------|
| `command` | Shell command (native execution) | — |
| `reasonix` | One-shot reasoning / coding agent | Reasonix CLI |
| `opencode` | Coding agent | OpenCode CLI |
| `gbrain` | Knowledge memory query/store | gbrain CLI |
| `subagent` | Delegated AI task | **Reasonix ACP** (v0.2.1+) |
| `skill` | Reusable skill/capability | External executor |
| `workflow` | Reference another workflow | — |

### subagent — Reasonix ACP (default since v0.2.1)

Subagent steps now default to **Reasonix ACP** — a headless coding agent with auto flash→pro escalation:

```yaml
- id: refactor_auth
  type: subagent
  context: "Refactor the authentication module to use async/await"
  workdir: /home/user/project
  model: auto        # default: flash→pro on hard turns
  effort: max
  timeout: 900
```

**Auto escalation:** When the model detects a task exceeds flash capacity, it emits `<<<NEEDS_PRO>>>` and Reasonix auto-retries on v4-pro. No manual model switching needed.

**Backward compat:** Set `provider: hermes` to use the pre-0.2.1 delegate_task behavior:

```yaml
- id: legacy_task
  type: subagent
  provider: hermes   # uses external executor (Hermes delegate_task)
  context: "Fix all the things"
```

Fields for subagent steps:
- `context` / `prompt` — task description
- `model` — `auto` (default, flash-first), `flash`, or `pro`
- `workdir` / `dir` — working directory (default: cwd)
- `effort` — `low` | `medium` | `high` | `max` (default: `max`)
- `timeout` — seconds (default: 900)
- `provider` — `reasonix` (default) or `hermes` (legacy)

Requires [Reasonix CLI](https://github.com/esengine/DeepSeek-Reasonix) and `DEEPSEEK_API_KEY` in environment.

### gbrain — Optional Knowledge Memory

yflow integrates with [gbrain](https://github.com/garrytan/gbrain) as an optional tool backend. gbrain is Garry Tan's knowledge memory system — a vector database for storing and retrieving structured knowledge across sessions.

```yaml
steps:
  # Query past knowledge before coding
  - id: check_known
    type: gbrain
    action: query
    query: "LanceDB dimension mismatch fix"
    output_as: past_solution

  # Save new knowledge
  - id: record_fix
    type: gbrain
    action: put
    slug: "new-bug-pattern"
    content: |
      # Bug: $check_known.output

  # Full-text search
  - id: find_patterns
    type: gbrain
    action: search
    query: "Riverpod context loss"

  # Read a page
  - id: read_page
    type: gbrain
    action: get
    slug: "lancedb-dimension-mismatch"
```

**Installation:** gbrain is NOT a pip dependency. Install it separately:

```bash
git clone https://github.com/garrytan/gbrain ~/gbrain
cd ~/gbrain && bun install
```

Set `GBRAIN_BIN` env var if gbrain is not on `$PATH`. yflow auto-detects `~/.local/bin/bun run ~/gbrain/src/cli.ts` as fallback.

## Variable Passing

### reasonix — DeepSeek-Native Agent (Run + Code)

yflow integrates with [Reasonix](https://github.com/esengine/DeepSeek-Reasonix), a DeepSeek-native agent framework with 99.82% cache hit rates in real-world use. Two modes:

**Run mode (default):** Read-only analysis, ultra-cheap (~$0.00003 per call):

```yaml
- id: analyze
  type: reasonix
  prompt: "Review this code for security issues"
  model: auto     # auto / flash / pro (default: auto)
```

**ACP mode:** Full coding agent — read, write, edit files, run terminal commands:

```yaml
- id: fix_bug
  type: reasonix
  mode: acp
  prompt: "Fix the race condition in worker.py"
  workdir: /home/user/project
  model: auto
  timeout: 600
```

The `auto` model preset starts on flash and auto-escalates to pro when the model self-reports `<<<NEEDS_PRO>>>` — keeping costs low on easy turns while getting pro reasoning for hard tasks.

Fields for reasonix steps:
- `prompt` — task description
- `mode` — `run` (default, read-only) or `acp` (coding with filesystem access)
- `model` — `auto` (default, flash→pro), `flash`, or `pro`
- `workdir` — working directory for acp mode (default: cwd)
- `timeout` — seconds (default: 300 run / 600 acp)

Requires [Reasonix CLI](https://github.com/esengine/DeepSeek-Reasonix) and `DEEPSEEK_API_KEY` in environment.

## Variable Passing

Steps can reference outputs from previous steps:

```yaml
- id: build
  type: command
  command: "npm run build"

- id: test
  type: command
  command: "echo 'Build output: $build.output'"
  depends_on: build
```

## Templates

Bootstrap common workflows from templates:

```bash
yflow create my-fix --from backend-bug-fix --set TASK_DESCRIPTION="Fix timeout in /api/search"
```

Built-in templates: `backend-bug-fix`, `backend-feature`, `flutter-bug-fix`, `flutter-feature`.

## Use with Any AI Agent

yflow is agent-agnostic. Pipe prompts to your agent of choice:

```bash
export YFLOW_EXEC="hermes -p"
yflow run my-pipeline --exec
```

Or use with any agent that can consume a prompt string.

## Roadmap

yflow follows a 10-phase roadmap. Completed phases ship in the Hermes workflow plugin first, then propagate to the standalone `yflow` package.

### Phase 1: Foundation ✅

| # | Feature | Status |
|---|---------|--------|
| P1 | `--from` template instantiation (`yflow create --from backend-bug-fix`) | ✅ |
| P2 | Native orchestration — engine directly spawns subagent steps (Reasonix ACP) | ✅ |
| P3 | `$step.output` variable passing between steps | ✅ |
| P4 | Sub-workflow — `type: workflow` recursive execution | ✅ |
| P5 | Task classifier — `classify_task()` auto-selects template | ✅ |

### Phase 2: Ecosystem ✅

| # | Feature | Status |
|---|---------|--------|
| P6 | Cron integration — `hermes cron create --workflow` | ✅ |
| P7 | Webhook → Workflow — GitHub push/PR/issue triggers workflow | ✅ |
| P8 | Marketplace — `community/` directory with shareable workflow YAMLs | ✅ |
| P10 | Analytics — `hermes workflow stats` with run history | ✅ |

### Phase 3: Future

| # | Feature | Status |
|---|---------|--------|
| P9 | Visual Builder — drag-and-drop workflow editor (TUI → Web) | 🔮 |

### Marketplace

Shareable workflows live in `~/.hermes/workflows/community/`:

| Workflow | Type | Description |
|----------|------|-------------|
| `system-health-check` | Monitoring | Daily disk, memory, bridge endpoint liveness |
| `alaya-build` | CI/CD | Flutter APK build pipeline: audit → build → ship |
| `pre-commit-review` | Code Review | Pre-commit gate with auto-fix + [verified] commit |
| `branch-review` | Code Review | Pre-merge: diff analysis + churn + conflict check |

```bash
hermes workflow run community/system-health-check --native
```

### Webhook

GitHub events trigger workflows automatically:

```bash
hermes workflow webhook --port 9001
```

| GitHub Event | → Workflow |
|-------------|-----------|
| `push` | `codebase-audit` |
| `pull_request` | `pre-commit-review` |
| `issues` | `branch-review` |

Configure routes in `~/.hermes/workflows/webhook.yaml`.

## Learn More

- [Examples](./examples/)
- [GitHub Repository](https://github.com/alanpaul1969/yflow)
- [Report an Issue](https://github.com/alanpaul1969/yflow/issues)

## License

MIT © Guo-luen Huang
