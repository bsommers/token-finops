# Architecture

## System Overview

`token-ops` is not software in the conventional sense — it is a single Claude Code **command** (`commands/token-ops.md`): a plain-Markdown behavioral protocol that Claude reads and follows when the user types `/token-ops`. There is no process, no server, no persisted state outside the conversation itself. The "system" is the conversation: Claude's own responses carry the state (the forecast, the running usage estimate) turn over turn.

The central architectural principle is **self-reporting under an explicit contract**: Claude is instructed to produce a specific, parseable status line on every turn, and to take a specific action (pause, summarize, prompt) when a threshold condition is met. There is no external verifier — the protocol relies on Claude estimating its own token consumption from observable signals (lines read, characters written, thinking effort) and adhering to the reporting format without being reminded each turn.

### Top-Level Architecture

```
     User                          Claude Code session                 Filesystem
      │                                    │                               │
      │  /token-ops <task>                 │                               │
      │───────────────────────────────────►│                               │
      │                                     │  read commands/token-ops.md   │
      │                                     │  (installed at                │
      │                                     │  ~/.claude/commands/)         │
      │                                     │                               │
      │                          ┌──────────▼──────────┐                   │
      │                          │  PHASE 1: FORECAST   │                   │
      │                          │  scope guessed files, │                   │
      │                          │  build budget table,  │                   │
      │                          │  state total as Y0    │                   │
      │                          └──────────┬──────────┘                   │
      │◄─────────── forecast table (Y0) ────│                               │
      │                                     │                               │
      │  (planning/scoping — a workflow      │                               │
      │   package's plan doc, a task list,   │                               │
      │   or just Read/Glob/Grep calls)      │                               │
      │                                     │                               │
      │                          ┌──────────▼──────────┐                   │
      │                          │  PHASE 1.5: RECALIBRATE│                 │
      │                          │  real file counts,    │                   │
      │                          │  real task breakdown  │                   │
      │                          │  (if any) → Y1         │                   │
      │                          │  (skipped if no        │                   │
      │                          │   scoping happened)    │                   │
      │                          └──────────┬──────────┘                   │
      │◄─────── [RECALIBRATED BUDGET: Y0→Y1] ────│                          │
      │                                     │                               │
      │  (build proceeds — first Write/Edit, │                               │
      │   then further tool calls, turns)    │                               │
      │                                     │                               │
      │                          ┌──────────▼──────────┐                   │
      │                          │  PHASE 2: MONITOR    │                   │
      │                          │  every turn: emit    │                   │
      │                          │  BUDGET STATS header │                   │
      │                          │  update X, Z          │                   │
      │                          └──────────┬──────────┘                   │
      │◄──── [BUDGET STATS: ...] + reply ───│                               │
      │                                     │                               │
      │                          X/Y ≥ 0.70 ?                               │
      │                                     │  yes                          │
      │                          ┌──────────▼──────────┐                   │
      │                          │  WARNING GATE         │                   │
      │                          │  pause new tool calls │                   │
      │                          └──────────┬──────────┘                   │
      │                                     │  write state summary          │
      │                                     │───────────────────────────────►│
      │                                     │                    scratchpad/  │
      │                                     │                    summary.md   │
      │◄────── prompt: /compact or /clear ──│                               │
      │                                     │                               │
```

---

## Component Map

### The command file — `commands/token-ops.md`

**Location**: `commands/token-ops.md` (repo), installed to `~/.claude/commands/token-ops.md` (runtime)
**Responsibility**: Defines the entire behavior of `/token-ops` — all three phases, the exact BUDGET STATS format, and the warning-gate actions.
**Interfaces**: Invoked as `/token-ops [task description]` in any Claude Code session. `$ARGUMENTS` is substituted with whatever text follows the command.
**Dependencies**: None beyond Claude Code's command-loading mechanism. It is plain Markdown — no frontmatter, no `allowed-tools` restriction, no external scripts or hooks. Phase 1.5 opportunistically reads planning artifacts if they exist (a GSD `PLAN.md`, a gstack plan-review output, a task list), but has no hard dependency on any of them — see [FORECASTING.md](FORECASTING.md).

**Internal structure** (sections within the single file):
```
token-ops.md
├── Preamble             — reads $ARGUMENTS, asks for a task if empty
├── Phase 1: Forecast     — pre-scoping budget table + rules, produces Y0
├── Phase 1.5: Recalibrate — post-scoping, pre-build re-forecast using real numbers, produces Y1
└── Phase 2: Monitor      — per-turn header format + 70% warning gate
```

This is `/token-ops`'s only component. There is no separate parser, renderer, or state store — Claude executes the instructions directly as part of normal turn generation.

### The security-scan estimator toolchain — `scripts/`, `schemas/` (draft, secondary)

**Location**: `scripts/index_repo.py`, `scripts/estimate_claude_security_cost.py`, `scripts/prerun_estimate.py`, `schemas/claude_security_pre_run_estimator.json`
**Responsibility**: A separate, explicitly draft capability — not part of `/token-ops` itself — that estimates the dollar cost of a Claude Security scan *before* it runs, from a repo's line count and a chosen scan-depth profile. See [SECURITY_SCAN_ESTIMATOR.md](SECURITY_SCAN_ESTIMATOR.md), [LOCAL_PRESCAN_INDEXING.md](LOCAL_PRESCAN_INDEXING.md), and [CLAUDE_SECURITY_USAGE.md](CLAUDE_SECURITY_USAGE.md).
**Interfaces**: Invoked directly as CLI scripts (`python3 scripts/prerun_estimate.py [--scope PATH] [--budget-usd N]`), not as a Claude Code command.
**Dependencies**: Python 3.9+, standard library only. No network calls, no model calls — `index_repo.py` reads the filesystem (via `git ls-files` when available) and `estimate_claude_security_cost.py` is a pure function over the JSON rate card.

```
scripts/
├── index_repo.py                     — offline LOC/directory indexer (git ls-files aware)
├── estimate_claude_security_cost.py  — pure cost-estimation function
└── prerun_estimate.py                — CLI: chains the two, prints a per-profile cost table
```

Unlike the command file above, this toolchain has no conversational state — each invocation is a stateless, one-shot CLI call whose only output is stdout (or a `--out` file from `index_repo.py`).

---

## Data Flow

### Primary Flow: One `/token-ops` invocation across a session

```
  ┌─ Turn 0 (invocation) ────────────────────────────────────────────┐
  │  User: /token-ops <task>                                          │
  │  Claude: (no tool calls yet)                                      │
  │          → builds forecast table:                                 │
  │              baseline ~25,000                                     │
  │            + file-read cost (guessed files × ~5 tok/line)         │
  │            + reasoning cap (2,000–15,000 by complexity)            │
  │            + output estimate                                      │
  │            = Y0 (provisional allocated budget)                    │
  │  Claude: "Allocated budget (Y0): ~Y0 tokens."                      │
  └────────────────────────────────────────────────────────────────┘
                              │
  ┌─ Planning / scoping (turns vary) ──▼───────────────────────────────┐
  │  Whatever actually happens before the first Write/Edit:            │
  │    - a workflow package's plan doc (GSD PLAN.md, gstack plan       │
  │      review, or any other package's output), OR                   │
  │    - a task list (TodoWrite/TaskCreate items), OR                  │
  │    - plain Read/Glob/Grep calls with no formal plan artifact       │
  │  If NONE of these happened, Phase 1.5 is skipped — Y0 stands.      │
  └────────────────────────────────────────────────────────────────┘
                              │  (first Write/Edit is about to happen)
  ┌─ Recalibration turn ──────▼───────────────────────────────────────┐
  │  Claude re-derives the same four line items using real numbers:   │
  │    - actual file line counts instead of guesses                   │
  │    - per-task sum from a plan/task list, if one exists             │
  │    - re-picked complexity tier                                     │
  │    - re-estimated output size                                      │
  │            = Y1 (revised allocated budget)                        │
  │  Claude: "[RECALIBRATED BUDGET: Y0 → Y1 (Δ%) | basis: ...]"        │
  │  X carries forward — NOT reset to zero at this point.              │
  └────────────────────────────────────────────────────────────────┘
                              │
  ┌─ Turn 1..N (build) ───────▼────────────────────────────────────────┐
  │  Claude opens EVERY reply with:                                    │
  │    [BUDGET STATS: Used approx: X / Allocated: Y                    │
  │                    | Current Context Depth: Z tokens               │
  │                    | Status: ON-TRACK / WARNING]                   │
  │                                                                     │
  │  Y is Y1 if recalibration happened, else Y0.                       │
  │  X updates incrementally each turn (never resets, never            │
  │  recomputed from scratch) as work happens.                         │
  │  Z tracks total conversation context, independent of Y.            │
  └────────────────────────────────────────────────────────────────┘
                              │  X / Y crosses 0.70
                              ▼
  ┌─ Warning turn ─────────────────────────────────────────────────────┐
  │  Status flips to WARNING. Claude:                                  │
  │    1. Stops starting new tool calls / edits                        │
  │    2. Writes a state summary to a scratchpad temp file             │
  │       (what's done, what's left, key paths, key decisions)         │
  │    3. Tells the user the file path and prompts /compact or /clear  │
  │    4. Waits — does not proceed automatically                       │
  └────────────────────────────────────────────────────────────────┘
                              │  (optional) user gives a new task
                              ▼
  ┌─ Rescope ───────────────────────────────────────────────────────────┐
  │  Treated as a fresh Phase 1: X resets, Y0 is recomputed, and         │
  │  Phase 1.5 runs again once the new task's planning is done.         │
  │  The old forecast is not silently carried forward.                 │
  └────────────────────────────────────────────────────────────────┘
```

### BUDGET STATS state machine

```mermaid
stateDiagram-v2
    [*] --> Forecasting : /token-ops invoked
    Forecasting --> Scoping : Phase 1 complete, Y0 set
    Scoping --> Recalibrating : planning/discovery happened before first build action
    Scoping --> OnTrack : no planning/discovery happened — Phase 1.5 skipped, Y = Y0
    Recalibrating --> OnTrack : Phase 1.5 complete, Y = Y1
    OnTrack --> OnTrack : turn completes, X < 0.70·Y
    OnTrack --> Warning : X crosses 0.70·Y
    Warning --> Warning : user has not run /compact or /clear
    Warning --> Forecasting : user issues a new task (rescope)
    OnTrack --> [*] : task complete
    Warning --> [*] : user compacts/clears and resumes
```

---

## Data Model

There is no persisted data model — all state lives in the conversation as plain values Claude tracks in its own reasoning and restates each turn:

```
Session budget state (conversational, not stored)
  ├── Y0 : int     — provisional allocated budget from Phase 1 (pre-scoping guess)
  ├── Y1 : int?    — revised allocated budget from Phase 1.5, if recalibration ran
  ├── Y : int      — the active allocation used by Phase 2 = Y1 if it exists, else Y0
  ├── X : int      — cumulative used estimate, tokens (monotonically non-decreasing per task,
  │                   carries forward across the Y0→Y1 recalibration — never reset by it)
  ├── Z : int      — current total context depth, tokens (independent of Y; can exceed Y)
  └── Status : enum — ON-TRACK | WARNING, derived as WARNING when X ≥ 0.70 × Y
```

The one artifact that *is* written to disk is the warning-gate summary file, placed under the scratchpad directory, containing: what's done, what's left, key file paths, and key decisions — enough for the user (or a fresh session after `/clear`) to resume.

---

## Key Design Decisions

### Estimate-based, not instrumented

**Context**: Claude Code does not expose an API for Claude to query its own exact token consumption mid-conversation.
**Options considered**: (a) Wait for tooling that exposes real counts; (b) have Claude estimate from observable signals (lines read, chars written, thinking effort).
**Decision**: (b) — heuristic self-estimation, biased toward overestimating rather than underestimating.
**Consequences**: The forecast and BUDGET STATS numbers are directionally useful, not exact. This is acceptable because the goal is an early warning, not precise accounting — see [PURPOSE.md](PURPOSE.md) for the non-goal of precision.

### Two separate numbers: task budget (X/Y) vs. context depth (Z)

**Context**: A task can be "on budget" for its own scope while the surrounding conversation's total context is still large (e.g., a long session with several prior tasks).
**Options considered**: Track only one number; track two.
**Decision**: Track both — X/Y for the current task's allocation, Z for total conversation context health.
**Consequences**: The warning gate fires on X/Y (task-scoped), but Z is surfaced every turn so context-window health stays visible even when the current task itself is on-track.

### Hard behavioral gate at 70%, not just a display number

**Context**: A budget readout that's purely informational is easy to ignore until the session is already in trouble.
**Options considered**: Display-only status line; display + mandatory pause-and-summarize action at a threshold.
**Decision**: The latter — crossing 70% forces a concrete sequence (pause, write summary, prompt for `/compact`/`/clear`, wait).
**Consequences**: Guarantees a recovery checkpoint exists before the context window is actually exhausted, at the cost of one extra round-trip when the threshold fires.

### Opportunistic recalibration, not a hard dependency on any planning package

**Context**: The Phase 1 forecast happens before any file is read, so `Y0` is necessarily a guess. Real information — actual file counts, actual task breakdown — typically exists once planning/scoping has happened, but *how* that planning happens varies enormously: a full GSD phase-planning cycle, a gstack plan-review skill, a one-off `Plan` subagent, or nothing more structured than Claude reading a few files before writing code.
**Options considered**: (a) Require a specific planning package (e.g., only recalibrate if GSD's `PLAN.md` exists); (b) define recalibration generically around *any* evidence of prior scoping, richest source first, with a no-op fallback.
**Decision**: (b) — Phase 1.5 triggers on a generic signal (a discovery tool call happened before the first build action) and opportunistically enriches itself with whatever structured plan artifact happens to exist, without requiring one.
**Consequences**: The recalibration step behaves identically whether the session has GSD, gstack, both, or neither installed — see the worked examples in [FORECASTING.md](FORECASTING.md#worked-examples). The cost is that recalibration quality is uneven: a session with a rich GSD `PLAN.md` gets a much sharper `Y1` than a session with only a couple of ad hoc file reads.

### Plain command, not a triggered skill

**Context**: Claude Code supports both explicit `/command`s and auto-triggered skills (matched by description).
**Options considered**: Skill (auto-triggers when Claude judges a task is complex); command (only runs when the user explicitly types it).
**Decision**: Command — this repo's parent collection ([bsommers/claude-skills](https://github.com/bsommers/claude-skills)) uses the convention that deliberately user-triggered actions are commands, not skills (see that repo's `ARCHITECTURE.md`).
**Consequences**: The user must remember to invoke `/token-ops` at the start of a task they want budgeted; it will not silently activate on its own judgment of task complexity.

---

## External Dependencies

| Dependency | Type | Purpose |
|------------|------|---------|
| Claude Code | CLI/runtime | Loads `~/.claude/commands/*.md` and executes `/command` invocations; provides the scratchpad directory the warning gate writes to |
| Python 3.9+ | Language runtime | Runs the draft estimator toolchain (`scripts/`) — standard library only, no packages installed |

No databases, queues, network calls, or third-party package dependencies.

---

## Known Limitations

- **No ground truth**: Token counts are Claude's own estimates from heuristics (~5 tokens/line for reads, rough effort-to-token mapping for thinking). They can drift from actual usage in either direction, though the protocol biases toward overestimating.
- **No cross-turn enforcement mechanism**: The BUDGET STATS header is a behavioral instruction, not a harness-enforced feature — if a very long session causes the instruction itself to fall out of the effective context, Claude could stop emitting it. There is no external watchdog.
- **Single-task scope**: The protocol resets on a new task rather than accumulating a session-wide ledger across multiple `/token-ops` invocations.
- **Recalibration quality depends on what planning actually happened**: Phase 1.5 is only as good as the discovery signal available to it — a task with a rich formal plan gets a sharp `Y1`; a task with only a couple of file reads gets a modest correction; a task with none at all gets no correction. The mechanism is uniform, but its output quality is not.
- **One recalibration point, not continuous**: Phase 1.5 fires once, right before the first build action. It does not re-recalibrate mid-build if the task's shape changes further after that point — a large mid-build scope change is only caught by Phase 2's ordinary `BUDGET STATS` drift, not by a second forecast.
