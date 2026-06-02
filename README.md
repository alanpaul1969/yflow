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
| `kanban` | Auto-decompose → parallel swarm → verify → synthesize | Hermes Kanban Swarm |

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
- `effort` — `low` | `medium` | `high` | `max` (default: `high` — matching Claude Opus 4.8)
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

### kanban — Auto-Decompose with Hermes Kanban Swarm

yflow now integrates with **Hermes Kanban Swarm** — the most powerful step type for tasks you can't decompose upfront. Instead of manually figuring out sub-steps, let the swarm do it:

```yaml
steps:
  - id: debug_websocket
    type: kanban
    goal: "Debug why WebSocket disconnects on Android after 30 seconds"
    workers:
      - profile: debugger
        skills: [systematic-debugging, flutter-pitfalls]
      - profile: architect
        skills: [flutter-backend-integration]
    verifier: code-reviewer
    synthesizer: architect
    timeout: 600
```

**How it works:** `type: kanban` spawns a 5-agent pipeline:
1. **Planning root** — auto-decomposes the goal into sub-tasks
2. **Parallel workers** — each specialist attacks a sub-task simultaneously
3. **Verifier** — gates results: pass or request rework
4. **Synthesizer** — merges verified outputs into a single deliverable

**Why this beats pure Kanban:**

| | Pure Kanban CLI | yflow `type: kanban` |
|---|---|---|
| Setup | `hermes kanban swarm` + `hermes kanban dispatch` — manual | One YAML line, integrated into your pipeline |
| Variable passing | Manual blackboard reads | `$step-id.output` between steps |
| Error handling | Manual monitoring | Auto-timeout + fallback to next step |
| Composite pipelines | Can't chain with other step types | Mix with `command`, `reasonix`, `gbrain` etc. |
| Pre/post processing | Must script separately | `command` steps before/after the swarm |
| Reusability | One-off CLI invocation | Templated, parameterized, version-controlled |
| Context | No cross-workflow awareness | `$previous_step.output` feeds into the goal |

**When to use `type: kanban` vs `type: subagent`:**

- `type: subagent` — you know the exact task. Single agent, one shot. Cheaper, faster.
- `type: kanban` — you don't know the sub-steps. Let the swarm decompose, explore in parallel, verify, and synthesize. Costs ~$0.01 but saves hours of manual decomposition.

Fields for kanban steps:
- `goal` (required) — the task goal
- `workers` — list of `{profile, skills, effort}` (default: 3 auto-assigned)
- `verifier` — verifier assignee (default: `code-reviewer`)
- `synthesizer` — synthesizer assignee (default: `architect`)
- `effort` — default effort for all workers: `low` | `medium` | `high` | `max` (default: `high`)
- `timeout` — seconds (default: 600)
- `verify` — verification gate (optional):
  - `gate` — `normal` | `strict` | `off` (default: `normal`)
  - `checks` — list of `[lint, test, self-review, type-check]`

Requires [Hermes Agent](https://github.com/NousResearch/hermes-agent) v0.15.0+ with Kanban Swarm.

### Effort Control — Per-Step Cost Optimization

yflow v0.4.0 introduces **per-step effort control** across all agent step types. Inspired by Claude Opus 4.8's effort parameter, you can now dial quality vs cost per step:

```yaml
steps:
  # Quick fix — cheap, low effort
  - id: fix_typo
    type: subagent
    context: "Fix the typo in README.md"
    effort: low          # ~$0.0003

  # Standard task — balanced (default)
  - id: refactor_module
    type: subagent
    context: "Refactor auth module to async/await"
    effort: high         # ~$0.001 — DEFAULT since v0.4.0

  # Critical security audit — maximum reasoning
  - id: security_audit
    type: kanban
    goal: "Audit entire auth module for vulnerabilities"
    effort: max          # ~$0.007 — full reasoning budget
    verify:
      gate: strict
      checks: [lint, test, type-check]
```

**Effort levels and cost:**

| Effort | Use case | Approx cost/subagent | Default? |
|--------|----------|---------------------|----------|
| `low` | Typo fixes, simple searches | ~$0.0003 | |
| `medium` | Small refactors, doc updates | ~$0.0005 | |
| `high` | Standard coding, debugging | ~$0.001 | ✅ (v0.4.0+) |
| `max` | Security audits, complex migrations | ~$0.003 | (was v0.3.0) |

Changing default from `max` → `high` saves ~67% on routine coding tasks while still providing strong reasoning for complex work. Set `effort: max` on critical steps that need it.

### Verify Gate — Quality Assurance

Kanban swarm steps now support a **verification gate** that controls how strictly the verifier gates worker outputs:

```yaml
- id: critical_fix
  type: kanban
  goal: "Fix the race condition in payment processing"
  verify:
    gate: strict        # strict | normal | off
    checks: [lint, test, self-review]
```

| Gate | Behavior |
|------|----------|
| `strict` | Verifier MUST run specified checks. Rejects if ANY check fails. No passing without evidence. |
| `normal` | Standard verification — reviews outputs but doesn't require formal checks. (default) |
| `off` | Auto-pass — verifier skips gate entirely. Use for exploratory work where verification is unnecessary. |

When `gate: strict` with `checks: [lint, test]`, the verifier will run linter and tests before accepting any worker's output. This mirrors Claude Opus 4.8's 4x improvement in catching flawed code before it reaches the user.

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

> **Hermes users:** The full plugin (engine + CLI + webhook + marketplace) lives at **[hermes-workflows](https://github.com/alanpaul1969/hermes-workflows)**. Install it alongside Hermes Agent for the native `/workflow` slash command, `hermes workflow webhook`, and `hermes workflow stats`.

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

## yflow memory — Second-Tier Storage (v0.5.0+)

Store persistent notes as markdown files in `~/.local/share/yflow/memory/`
(XDG-compliant). Each entry has YAML frontmatter (title, type, tags, updated)
plus a markdown body. Zero new dependencies.

```bash
# Add a memory entry
yflow memory add infra/minimax-m3-config \
  --title "M3 model config" \
  --type infrastructure \
  --tags "minimax,m3" \
  --from-file config.md

# List, search, inject into LLM context
yflow memory list
yflow memory search "M3"
yflow memory inject infra/minimax-m3-config infra/pipeline-canonical-numbers

# Inject into workflow steps automatically:
yflow memory check   # budget + staleness report
yflow memory diet    # interactive cleanup
```

Override storage via `$YFLOW_MEMORY_DIR`. See `examples/memory-injection-demo.yaml`.

## Memory Injection in Workflows (v0.5.0+)

Workflows can declare persistent context to inject into every step:

```yaml
name: my-workflow
memory:
  cold_load:                       # auto-injected as context for each step
    - infra/minimax-m3-config
    - infra/pipeline-canonical-numbers
  budget_chars: 4000               # warning if total exceeds
  markers: ["★", "[!]", "→"]      # canonical markers
```

Each step gets the merged content prepended to its prompt. No need for the
LLM to query memory each time. Works with all step types that take a
`prompt`/`context` field (subagent, reasonix, opencode, **minimax**).

## Native M3 Step Type (v0.5.0+)

Use MiniMax M3 directly as a step, without going through Hermes or Reasonix.
Uses stdlib `urllib.request` — zero new deps.

```yaml
steps:
  - id: review_with_m3
    type: minimax
    effort: high          # low|medium|high|max (default: high)
    model: MiniMax-M3
    prompt: "Review this diff for security issues..."
```

Auth (any of):
- `api_key: sk-...` in step
- `$YFLOW_MINIMAX_API_KEY` env var
- `~/.config/yflow/auth.json` → `{"minimax_api_key": "sk-..."}`

## Delay-Tolerant Template (v0.5.0+)

For multi-session changes (user not in real-time):

```bash
yflow create my-big-change --from delay-tolerant \
  --set DESCRIPTION="Add new gbrain endpoint" \
  --set NAME_SLUG=add-gbrain-endpoint
```

Generates a 7-phase workflow: bootstrap → discovery → ux → openspec → workflow → implement → audit
with mandatory backup, abort criteria, and status_page_slug for cross-session resumption.

## Learn More

- [Examples](./examples/) — `memory-injection-demo.yaml`, `delay-tolerant-feature.yaml`
- [GitHub Repository](https://github.com/alanpaul1969/yflow)
- [Report an Issue](https://github.com/alanpaul1969/yflow/issues)

## License

MIT © Guo-luen Huang
