# token-finops

> A Claude Code slash command that forecasts and monitors token/context budget for a coding task, so long sessions don't silently blow past the context window.

Long agentic coding sessions in [Claude Code](https://claude.ai/code) accumulate context — file reads, tool output, thinking, generated code — with no visible running total. By the time a session feels sluggish or starts truncating history, the budget is already gone and there was no checkpoint to compact or clear at. `/token-ops` fixes that: it makes you forecast a token budget before starting a task, then carries a live utilization readout on every turn until you hit a warning threshold and get prompted to intervene.

This repo is deliberately small: one command, driving one behavioral protocol.

---

## Quick Start

```bash
# 1. Install — copy the command into your global Claude Code commands directory
cp commands/token-ops.md ~/.claude/commands/token-ops.md

# 2. Use it — inside any Claude Code session
/token-ops implement rate limiting on the /api/upload endpoint
```

Claude responds with a forecast table, then opens every subsequent turn with a `[BUDGET STATS: ...]` line until the task wraps or the budget warning fires.

---

## What It Does

- **Forces a forecast before work starts** — Claude must name the files it expects to touch and estimate baseline, file-read, reasoning, and output costs before running a single tool call.
- **Tracks utilization every turn** — a one-line `BUDGET STATS` header reports used-vs-allocated tokens and overall context depth, so drift is visible turn over turn instead of discovered after the fact.
- **Warns at 70% utilization** — crossing the threshold pauses new work, writes a state summary to a scratch file, and prompts you to `/compact` or `/clear` before continuing.
- **Rescopes cleanly on new tasks** — a new task mid-session resets the forecast rather than silently inheriting the old budget.

---

## Architecture Overview

```
          ┌───────────────────────────────────────────────────┐
          │                    Claude Code                    │
          │                                                   │
  /token-ops │  ┌──────────────┐        ┌──────────────────┐ │
 ──────────►│  │   Phase 1     │───────►│     Phase 2       │ │
  <task>     │  │   Forecast    │        │   Per-turn        │ │
          │  │  (before any   │        │   BUDGET STATS     │ │
          │  │  tool calls)   │        │   header + 70%      │ │
          │  └──────────────┘        │   WARNING gate      │ │
          │                           └─────────┬──────────┘ │
          └─────────────────────────────────────┼────────────┘
                                                  │ WARNING
                                                  ▼
                                   ╔══════════════════════════╗
                                   ║  scratchpad summary file  ║
                                   ║  + prompt: /compact       ║
                                   ║           or /clear       ║
                                   ╚══════════════════════════╝
```

---

## Project Structure

```
token-finops/
├── commands/
│   └── token-ops.md     — the /token-ops command definition (plain Markdown, no frontmatter)
├── README.md             — this file
├── ARCHITECTURE.md       — protocol design, state model, diagrams
├── PURPOSE.md            — why this exists, goals, non-goals
├── HOWTO.md              — task-oriented usage guide
└── .gitignore            — excludes local, machine-specific Claude Code settings
```

There is no build, no dependencies, no runtime beyond Claude Code itself. The command is a single Markdown file of instructions that Claude follows when `/token-ops` is invoked.

---

## Configuration

None. The command takes its only input as free-text arguments after `/token-ops` — the task description — and asks for one if it's omitted.

---

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](ARCHITECTURE.md) | The two-phase protocol, BUDGET STATS field semantics, warning-gate state machine |
| [Purpose](PURPOSE.md) | The problem this solves, goals, non-goals, trade-offs |
| [How-To Guide](HOWTO.md) | Install, invoke, read the output, tune the threshold, debug |

---

## License

Private — bsommers.
