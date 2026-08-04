# Forecasting Methodology

This document explains *how* the numbers in a `/token-ops` forecast are calculated — where each line item comes from, why the defaults are what they are, and how the forecast gets sharper once real planning information exists. The command file ([`commands/token-ops.md`](commands/token-ops.md)) is the operative contract Claude follows; this doc is the reference for the reasoning behind it.

Claude Code has no API that exposes Claude's own exact token consumption mid-session. Every number here is therefore a **heuristic estimate from observable signals** (line counts, character counts, task complexity), not an instrumented measurement. The goal of the methodology is to be directionally reliable and consistently biased toward overestimating — not to be exact. See [PURPOSE.md](PURPOSE.md) for why exactness is explicitly a non-goal.

---

## The four line items, and how each is derived

### 1. Initial baseline (~25,000 tokens)

This covers everything loaded into context before the task-specific work begins:

| Component | What it is | Scales with |
|---|---|---|
| Harness system prompt | Claude Code's own instructions | Fixed per Claude Code version |
| Tool schemas | JSON schemas for every built-in tool and connected MCP server | Number of tools/MCP servers active |
| `CLAUDE.md` files | Global (`~/.claude/CLAUDE.md`) + project-level instructions | File size, ~5 tokens/line (same ratio as source — see below) |
| Skill/agent/command listings | Name + one-line description for every installed skill, shown so Claude can route to them | Number of installed skills/plugins |

~25,000 is a reasonable default for a typical setup: a moderate `CLAUDE.md`, the standard built-in tool set, and a handful of skills. It is **not** universal — a project with a large `CLAUDE.md` or many installed skill packages (GSD alone registers 70+ skills) pushes this materially higher.

**How to sharpen this number**: use `wc -l` on the active `CLAUDE.md` files and add roughly 5 tokens per line on top of an ~18,000-token floor for harness + tools. If you're running with a large plugin surface (GSD, gstack, security-* skills, etc. all installed), lean toward the higher end of a ~25,000–35,000 range rather than the flat default.

### 2. File read cost (~5 tokens per line)

Derived from two facts about English prose and typical source code:
- Common tokenizers average roughly **4 characters per token** for English/code text.
- A typical source line (including indentation, short identifiers, and syntax) averages **~20–25 characters**.

That puts most files at ~5–6 tokens/line. The `Read` tool also prefixes every line with a line number and a tab, adding a small constant per-line overhead — rounded into the same ~5 tokens/line figure for simplicity.

This is an average, not a constant. Adjust it for known-dense or known-sparse formats:

| Format | Adjusted rate | Why |
|---|---|---|
| Minified JS/CSS, long JSON/YAML values, log lines | ~8–12 tokens/line | Long lines, high information density |
| Typical application code (JS/TS/Python/Go/etc.) | ~5 tokens/line | The default |
| Markdown prose, comments-heavy code | ~5–6 tokens/line | Similar density to code |
| Whitespace-heavy formatting, generated boilerplate, blank-line-separated code | ~3–4 tokens/line | Lower information density per line |

Applies identically to **output** generation — code or diffs Claude expects to write use the same per-line rate, just multiplied by expected new/changed lines instead of lines read.

### 3. Reasoning/thinking budget (tiered, not a single guess)

Thinking budget should scale with **decision complexity**, not simply file count — a five-file mechanical rename is simpler than a one-file algorithm redesign. Use the tier table:

| Tier | Signal | Budget |
|---|---|---|
| Trivial | Single file, single well-defined change, no ambiguity | ~1,000–2,000 |
| Simple | 1–3 files, follows an established pattern already in the codebase | ~2,000–4,000 |
| Moderate | Multiple files, some design decisions, new code paths | ~4,000–8,000 |
| Complex | Cross-cutting change, multiple subsystems, non-obvious trade-offs | ~8,000–15,000 |
| Very complex / research-heavy | Unknown unknowns — requires exploration before design is even possible | ~15,000–30,000+ |

Picking a tier is itself a forecast — Phase 1.5 (below) exists because the right tier is often only clear *after* some scoping has happened.

### 4. Output generation

Two components, summed:
- **Code/diff output** — expected new or changed lines × the same per-line rate as file reads (item 2).
- **Conversational prose** — the reply text itself. Ordinary Claude Code turns run short (a few sentences to a couple of paragraphs, roughly 150–500 tokens); a requested report, doc suite, or long explanation runs materially longer and should be estimated from its expected length, not assumed to be a normal-sized reply.

---

## Why the initial forecast is provisional

Phase 1's forecast (`Y0`) happens *before* any file has been read — it is necessarily a guess built from the task description alone: guessed file names, guessed line counts, a guessed complexity tier. That's fine as a first pass (it forces scoping thought before any tool calls), but it shouldn't be treated as authoritative once real information exists.

**Phase 1.5** is the point where the forecast gets recalibrated with facts instead of guesses — right after planning/scoping activity and right before the first line of code is actually written. This is the moment where a plan (formal or not) exists but no build tokens have been spent yet, making it the cheapest possible point to correct a bad initial estimate.

### What "planning activity" means, concretely

Phase 1.5 doesn't require any particular workflow package — it looks for whichever signal actually exists in the session, richest first:

```
                    Did a plan artifact get produced?
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
       Structured plan     Ad hoc task list   Nothing structured
       (GSD PLAN.md/SPEC.md,   (TodoWrite /       (just files opened
       gstack plan-review       TaskCreate items    during scoping —
       output, or any other     from planning)       Read/Glob/Grep
       package's plan doc)                            calls already made)
              │                 │                 │
              ▼                 ▼                 ▼
     Sum per-task cost   Use item count as   Use real files + real
     from the plan's      complexity signal   line counts already
     actual breakdown                          seen this session
              │                 │                 │
              └─────────────────┼─────────────────┘
                                 ▼
                   Recompute Y using Phase 1's method,
                   with real numbers instead of guesses.
                   Report as a delta: Y0 → Y1.
```

If none of these exist — the task was simple enough that no scoping happened before the first edit — Phase 1.5 is skipped and `Y0` carries forward unchanged. Recalibration is an enrichment step, never a blocking one, which is what makes it work identically whether the session has GSD, gstack, both, or neither installed.

---

## Worked examples

### With GSD

Task: "Implement the notifications phase" after running `/gsd-plan-phase`, which produced `.planning/phases/03-notifications/PLAN.md` with 6 discrete tasks and a files-touched list.

```
Phase 1 (pre-plan):  Y0 ≈ 38,000   (guessed: "probably 3-4 files, moderate complexity")

... /gsd-plan-phase runs, PLAN.md is written with 6 tasks and 9 named files ...

Phase 1.5 (recalibration):
  - 9 files confirmed (was 3-4 guessed) — file read cost revises up
  - 6 discrete tasks in PLAN.md, summed individually — thinking budget revises up
  - Y1 ≈ 61,000

[RECALIBRATED BUDGET: Y0 → Y1 (Δ+60%) | basis: PLAN.md — 9 files, 6 tasks (was 3-4 files guessed)]
```

### With gstack

Task: a feature scoped through `/plan-eng-review`, which surfaces an engineering review with a concrete implementation checklist.

```
Phase 1 (pre-plan):  Y0 ≈ 30,000   (guessed complexity: moderate)

... /plan-eng-review runs, checklist reveals a schema migration + 2 new endpoints ...

Phase 1.5 (recalibration):
  - Checklist implies complex tier, not moderate (schema migration = cross-cutting)
  - Y1 ≈ 52,000

[RECALIBRATED BUDGET: Y0 → Y1 (Δ+73%) | basis: plan-eng-review checklist — schema migration revises complexity moderate→complex]
```

### With neither (plain Claude Code, no framework)

Task: "add rate limiting to the upload endpoint," no planning skill invoked — just Claude reading the relevant files before writing code.

```
Phase 1 (pre-plan):  Y0 ≈ 34,000   (guessed: middleware file + route file + one test file)

... Claude reads src/middleware/, src/routes/upload.ts, and greps for existing
    rate-limit patterns before writing anything ...

Phase 1.5 (recalibration):
  - Actual line counts now known: middleware dir (140 lines), upload.ts (90 lines),
    an existing similar middleware found via grep (adds a 4th file to touch)
  - Y1 ≈ 41,000

[RECALIBRATED BUDGET: Y0 → Y1 (Δ+21%) | basis: 4 files confirmed via Read/Grep (was 3 estimated)]
```

In every case the mechanism is identical — the only thing that changes is *where the recalibration signal comes from*. No framework-specific logic lives in `/token-ops` itself.

---

## Known error sources

- **Baseline drift** — a session that starts with a small `CLAUDE.md` and gradually loads more MCP servers or skills over its lifetime will under-count the baseline for later tasks unless it's periodically re-checked.
- **Per-line rate mismatch** — code with unusually long lines (dense method chains, wide tables) or unusually short ones (one-statement-per-line style) will drift from the ~5 tokens/line default; adjust using the table in section 2 when you recognize the pattern.
- **Thinking tier misjudgment** — the tier table is a heuristic, not a formula; a task can look "moderate" from its description and turn out "complex" once dependencies are discovered. This is exactly what Phase 1.5 exists to correct — treat a large Phase 1.5 delta as a signal the tier was wrong, not as an error in the recalibration itself.
