# token-finops

> A Claude Code slash command that forecasts and monitors token/context budget for a coding task, so long sessions don't silently blow past the context window.

**Value proposition, in one line:** this repo puts a real number on token spend *before* you commit to it — a token budget forecast before a coding task starts (`/token-ops`), and a **dollar-figure cost estimate before a Claude Security scan runs** (the draft pre-flight estimator below). Both exist because Claude Code and Claude Security only tell you cost *after* the fact, or in vague terms ("relative cost") *before* it — never a number you can budget against ahead of time.

**The specific pre-flight value-add**: the Claude Security plugin's own scoping step tells you a scan's cost only qualitatively — "the plugin reads your repository first, then offers the whole repository or a focused area, with each option's file count and *relative* cost stated." No dollar figure, no token count. This repo's `prerun_estimate.py` closes that gap — indexing your repo locally (offline, no network calls) and turning that vague signal into an actual table:

```
| Profile               | Est. cost (USD) |
|------------------------|-----------------|
| pr_quick_scan          | $1.85           |
| standard_taint_audit   | $38.59          |
| deep_exploit_hunt      | $229.24         |
```

That's the difference between "this scan is probably cheap" and knowing, before you confirm the run, that a `deep_exploit_hunt`-depth scan on this repo is a $229 decision, not a $2 one, on the Mythos-5-backed Enterprise product's own confirmed rate card — see [CLAUDE_SECURITY_USAGE.md](docs/CLAUDE_SECURITY_USAGE.md).

**➡️ [Run a pre-flight scan estimate for the Claude Security Enterprise service](docs/RUN_ENTERPRISE_PREFLIGHT.md)** — the step-by-step walkthrough for getting the dollar figure above against your own repo before a real `claude.ai/security` scan.

Long agentic coding sessions in [Claude Code](https://claude.ai/code) accumulate context — file reads, tool output, thinking, generated code — with no visible running total. By the time a session feels sluggish or starts truncating history, the budget is already gone and there was no checkpoint to compact or clear at. `/token-ops` fixes that: it makes you forecast a token budget before starting a task, then carries a live utilization readout on every turn until you hit a warning threshold and get prompted to intervene.

This repo is deliberately small: one command, driving one behavioral protocol. It also holds a draft, in-progress companion — a *pre-run* dollar-cost estimator for agentic security-scan workloads (as opposed to `/token-ops`'s live session monitoring), including a local, offline repo indexer and a mapping onto the real Claude Security public beta — see [SECURITY_SCAN_ESTIMATOR.md](docs/SECURITY_SCAN_ESTIMATOR.md), [LOCAL_PRESCAN_INDEXING.md](docs/LOCAL_PRESCAN_INDEXING.md), and [CLAUDE_SECURITY_USAGE.md](docs/CLAUDE_SECURITY_USAGE.md).

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
- **Recalibrates once real scoping exists** — after planning/discovery and before the first edit, the forecast is redone with actual file counts and complexity instead of guesses. Works with a formal plan (GSD, gstack, etc.) or with nothing more than Claude's own file reads — see [FORECASTING.md](docs/FORECASTING.md).
- **Tracks utilization every turn** — a one-line `BUDGET STATS` header reports used-vs-allocated tokens and overall context depth, so drift is visible turn over turn instead of discovered after the fact.
- **Warns at 70% utilization** — crossing the threshold pauses new work, writes a state summary to a scratch file, and prompts you to `/compact` or `/clear` before continuing.
- **Rescopes cleanly on new tasks** — a new task mid-session resets the forecast rather than silently inheriting the old budget.

---

## Architecture Overview

```
  /token-ops <task>
        │
        ▼
┌───────────────────────────────────────────────────────────────────────┐
│                              Claude Code                               │
│                                                                         │
│  ┌─────────────┐      ┌──────────────────┐      ┌────────────────┐    │
│  │   Phase 1    │─────►│    Phase 1.5      │─────►│    Phase 2      │    │
│  │   Forecast   │      │   Recalibration   │      │   Per-turn      │    │
│  │ (pre-scoping,│      │  (post-scoping,   │      │  BUDGET STATS   │    │
│  │  guessed Y0) │      │  pre-build, Y1)   │      │  + 70% WARNING  │    │
│  └─────────────┘      └──────────────────┘      └────────┬────────┘    │
│                                                            │             │
└────────────────────────────────────────────────────────────┼─────────────┘
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
├── schemas/
│   └── claude_security_pre_run_estimator.json  — rate card + scan-profile config (draft)
├── scripts/
│   ├── estimate_claude_security_cost.py         — reference estimator implementation (draft)
│   ├── index_repo.py                            — local, offline LOC/file indexer (draft)
│   └── prerun_estimate.py                       — CLI: index + estimate in one pass (draft)
├── docs/
│   ├── ARCHITECTURE.md              — protocol design, state model, diagrams
│   ├── PURPOSE.md                   — why this exists, goals, non-goals
│   ├── FORECASTING.md               — how the budget numbers are calculated and recalibrated
│   ├── HOWTO.md                     — task-oriented usage guide
│   ├── SECURITY_SCAN_ESTIMATOR.md   — draft pre-run cost estimator for agentic security scans
│   ├── LOCAL_PRESCAN_INDEXING.md    — local indexing exploration: does it cut scan tokens, and how
│   ├── CLAUDE_SECURITY_USAGE.md     — how this maps onto the real Claude Security public beta
│   └── RUN_ENTERPRISE_PREFLIGHT.md  — step-by-step: estimate a Claude Security Enterprise scan's cost
├── README.md             — this file
└── .gitignore            — excludes local, machine-specific Claude Code settings
```

`/token-ops` itself has no build, no dependencies, no runtime beyond Claude Code — it's a single Markdown file of instructions Claude follows when invoked. The draft `scripts/` toolchain needs only Python 3.9+ (standard library, nothing installed).

---

## Configuration

None for `/token-ops` — it takes its only input as free-text arguments after `/token-ops` (the task description) and asks for one if it's omitted. The draft estimator's config is the rate card and scan-profile definitions in [`schemas/claude_security_pre_run_estimator.json`](schemas/claude_security_pre_run_estimator.json) — the rate card (Claude Mythos 5, the fixed model behind the managed Claude Security Enterprise product) is confirmed against Anthropic's published pricing; the scan-depth step-count multipliers are still unverified defaults — see [docs/SECURITY_SCAN_ESTIMATOR.md](docs/SECURITY_SCAN_ESTIMATOR.md).

---

## Development

There's no build step or test suite — `/token-ops` is validated by using it in a real Claude Code session, and the estimator scripts are plain stateless CLI tools:

```bash
# Sanity-check the estimator scripts parse and run
python3 -c "import ast; [ast.parse(open(f).read(), f) for f in ['scripts/index_repo.py', 'scripts/prerun_estimate.py', 'scripts/estimate_claude_security_cost.py']]"
python3 scripts/prerun_estimate.py --budget-usd 10
```

To iterate on `/token-ops` itself, edit `commands/token-ops.md`, copy it to `~/.claude/commands/token-ops.md`, and run it in a live session — see [Update the command](docs/HOWTO.md#update-the-command).

---

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/ARCHITECTURE.md) | The three-phase protocol, BUDGET STATS field semantics, warning-gate state machine |
| [Forecasting Methodology](docs/FORECASTING.md) | How the baseline, file-read, thinking, and output estimates are calculated, and how Phase 1.5 recalibrates them once real planning info exists — with or without GSD/gstack |
| [Purpose](docs/PURPOSE.md) | The problem this solves, goals, non-goals, trade-offs |
| [How-To Guide](docs/HOWTO.md) | Install, invoke, read the output, tune the threshold, debug |
| [Security Scan Estimator](docs/SECURITY_SCAN_ESTIMATOR.md) *(draft)* | Pre-run dollar-cost model for agentic security scans, separate from `/token-ops`'s session monitoring |
| [Local Pre-Scan Indexing](docs/LOCAL_PRESCAN_INDEXING.md) *(draft)* | Offline LOC/directory indexer feeding the estimator, and what it can/can't do to cut scan tokens |
| [Claude Security Usage](docs/CLAUDE_SECURITY_USAGE.md) *(draft)* | How this repo's tooling maps onto the real Claude Security public beta (managed product + Claude Code plugin) |
| [Run an Enterprise Pre-Flight Scan](docs/RUN_ENTERPRISE_PREFLIGHT.md) | Step-by-step walkthrough: get a dollar estimate for a Mythos-5-backed Claude Security Enterprise scan before running it |

---

## Contributing

Private, single-maintainer repo — not open for external contributions. If you're the maintainer: edit here first (this is canonical), then sync the read-only mirror in [bsommers/claude-skills](https://github.com/bsommers/claude-skills) (`docs/token-ops/*.md`, banner-tagged with the commit it was last synced from) before committing.

---

## License

Private — bsommers.
