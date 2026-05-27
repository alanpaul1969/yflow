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

| Type | Description | Needs external agent? |
|------|-------------|-----------------------|
| `command` | Shell command (native execution) | No |
| `reasonix` | One-shot reasoning agent | Yes (reasonix CLI) |
| `opencode` | Coding agent | Yes (opencode CLI) |
| `gbrain` | Knowledge memory query/store | Optional (gbrain CLI) |
| `subagent` | Delegated AI task | Yes |
| `skill` | Reusable skill/capability | Yes |
| `workflow` | Reference another workflow | No |

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

## Learn More

- [Examples](./examples/)
- [GitHub Repository](https://github.com/alanpaul1969/yflow)
- [Report an Issue](https://github.com/alanpaul1969/yflow/issues)

## License

MIT © Guo-luen Huang
