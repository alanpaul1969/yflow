# YAMLflow

> **The Makefile for AI workflows** — 1 dependency, zero daemons, provider-agnostic.

Define multi-agent workflows in YAML. Run them anywhere. No Docker, no servers, no lock-in.

## Why YAMLflow?

AI agent platforms are powerful but heavyweight — dozens of dependencies, daemons, Docker, and vendor lock-in. YAMLflow is different:

| Feature | YAMLflow | awf | AutoTeam | Animus | AQM |
|---------|----------|-----|----------|--------|-----|
| Dependencies | 1 (PyYAML) | 20+ | 30+ | 15+ | 25+ |
| Daemon required | ❌ | ✅ | ✅ | ✅ | ✅ |
| Docker required | ❌ | ✅ | ✅ | ❌ | ✅ |
| Provider-agnostic | ✅ | ✅ | ❌ | ✅ | ❌ |
| Native command exec | ✅ | ❌ | ❌ | ❌ | ❌ |
| Variable passing | ✅ | ❌ | ✅ | ❌ | ❌ |
| Sub-workflows | ✅ | ❌ | ❌ | ❌ | ❌ |
| Template system | ✅ | ❌ | ❌ | ❌ | ❌ |

## Install

```bash
pip install yamlflow
```

That's it. No Docker, no daemon, no API keys. Just `yamlflow` on your PATH.

## Quick Start

### 1. Create a workflow

```bash
yamlflow create hello-world
```

### 2. Edit it

```yaml
name: "Hello World"
description: "My first YAMLflow pipeline"

steps:
  - id: greet
    name: "Say hello"
    type: command
    command: "echo 'Hello from YAMLflow!'"

  - id: verify
    name: "Verify output"
    type: command
    command: "echo 'Previous step said: $greet.output'"
    depends_on: greet
```

### 3. Run it

```bash
yamlflow run hello-world --native
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
| `subagent` | Delegated AI task | Yes |
| `skill` | Reusable skill/capability | Yes |
| `workflow` | Reference another workflow | No |

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
yamlflow create my-fix --from backend-bug-fix --set TASK_DESCRIPTION="Fix timeout in /api/search"
```

Built-in templates: `backend-bug-fix`, `backend-feature`, `flutter-bug-fix`, `flutter-feature`.

## Use with Any AI Agent

YAMLflow is agent-agnostic. Pipe prompts to your agent of choice:

```bash
export YAMLFLOW_EXEC="hermes -p"
yamlflow run my-pipeline --exec
```

Or use with any agent that can consume a prompt string.

## Learn More

- [Examples](./examples/)
- [GitHub Repository](https://github.com/alanpaul1969/yamlflow)
- [Report an Issue](https://github.com/alanpaul1969/yamlflow/issues)

## License

MIT © Guo-luen Huang
