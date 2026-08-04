# Purpose

## Problem Statement

Long Claude Code sessions accumulate context silently: every file read, tool result, and turn of thinking adds tokens with no running total visible to the user or to Claude itself. There is no natural checkpoint prompting a `/compact` or `/clear` before the window fills — the first signal is usually degraded behavior (truncated history, dropped earlier context, or the session simply becoming sluggish) after the budget is already gone. At that point, recovering cleanly means reconstructing lost state from scratch, because nothing was written down at the moment things started to go wrong.

## Solution

`/token-ops` turns an invisible resource (token budget) into a visible, reported-on one. Before any work starts, Claude is forced to forecast a budget in writing, naming the files it expects to touch. For the rest of the session, every reply opens with a compact self-reported usage line. Crossing 70% of the forecast triggers a concrete recovery action — write a resumable summary to disk, then stop and ask the user to `/compact` or `/clear` — so there's always a checkpoint before things get bad, not after.

---

## Goals

1. **Make token usage visible per-turn** — a running estimate the user can see without asking, so budget drift is caught early rather than discovered as degraded behavior.
2. **Force a scoping step before work starts** — naming expected files and estimating cost is itself a forcing function for thinking through task scope, independent of the budget number's precision.
3. **Guarantee a resumable checkpoint before exhaustion** — the warning gate's scratchpad summary means a `/clear` never loses unrecoverable state.
4. **Stay lightweight** — a single Markdown command file, no dependencies, no setup beyond copying one file.

## Non-Goals

- **Not exact token accounting** — Claude Code doesn't expose real-time token counts to Claude mid-session, so this protocol is explicitly heuristic. It optimizes for early warning, not audit-grade precision. Anyone needing exact numbers should use Claude Code's own `/cost` or session-level usage reporting, not this command's self-estimates.
- **Not automatic compaction** — the command prompts the user to run `/compact` or `/clear`; it deliberately does not invoke them automatically, since that decision (and the judgment about what's safe to drop) belongs to the user.
- **Not a multi-task session ledger** — each `/token-ops` invocation scopes to one task. It does not attempt to track cumulative usage across every task in a long-running session.
- **Not a cost/billing tool** — this is about context-window health during a session, not dollar-cost tracking or API billing reconciliation.

---

## Users and Stakeholders

| Audience | How they interact | What they need from this |
|----------|------------------|--------------------------|
| Developer running Claude Code | Types `/token-ops <task>` at the start of a task they expect to be long or multi-file | Early, honest warning before a session degrades, and a checkpoint to resume from |
| Future Claude session (post-`/clear`) | Reads the scratchpad summary file left by the warning gate | Enough written state to resume without re-deriving everything from git history |

---

## Success Criteria

- [ ] A `/token-ops` session reliably opens every turn with a well-formed `[BUDGET STATS: ...]` line
- [ ] The forecast in Phase 1 names concrete files rather than a bare number
- [ ] Crossing 70% utilization reliably triggers the pause → summarize → prompt sequence before the user notices degraded behavior on their own
- [ ] A user who follows the `/compact` or `/clear` prompt can resume the task using only the scratchpad summary

---

## Context and History

This command was written after observing that Claude Code sessions have no built-in mid-session token budget forecast or checkpoint prompt — usage is visible in aggregate (e.g., after the fact via `/cost`) but not tied to a specific task's forecast, and there's no forced moment to plan a checkpoint before a long task begins. `/token-ops` was designed to add that moment without requiring any change to Claude Code itself — it's implemented entirely as a behavioral contract in a command file.

---

## Relationship to Other Systems

```
  ╔═══════════════════╗        ┌──────────────────────┐        ╔═══════════════════╗
  ║   Claude Code       ║        │   /token-ops          │        ║  Claude Code       ║
  ║   command loader     ║──────►│   commands/token-ops.md│───────►║  built-in          ║
  ║   (~/.claude/commands)║       │   (this repo)          │        ║  /compact, /clear  ║
  ╚═══════════════════╝        └──────────────────────┘        ╚═══════════════════╝
```

`/token-ops` sits upstream of Claude Code's own `/compact` and `/clear` commands — it never calls them, only recommends them at the right moment. It has no relationship to Claude Code's actual token accounting or billing systems; its numbers are independent, self-reported estimates.

---

## Trade-offs Made

- **Self-estimation over precision**: Chose heuristic self-reporting over waiting for (or building) real token instrumentation, because the value — an early, visible warning — doesn't require exactness. Cost: the numbers can be wrong, sometimes significantly.
- **Behavioral protocol over tooling/hooks**: Chose a plain Markdown command over a Claude Code hook or plugin that could enforce the header mechanically. Cost: the protocol depends on Claude continuing to follow instructions turn after turn, with no external enforcement if it drifts in a very long session.
- **User-initiated over automatic**: Chose to require the user to type `/token-ops` rather than auto-triggering on any complex task. Cost: a user who forgets to invoke it gets no forecast or monitoring at all. Benefit: no surprise behavior change on unrelated tasks, consistent with this repo's convention that explicitly user-triggered actions are commands, not auto-triggered skills.
