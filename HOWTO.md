# How-To Guide

## Contents

- [Install the command](#install-the-command)
- [Invoke /token-ops](#invoke-token-ops)
- [Read the forecast table](#read-the-forecast-table)
- [Read the recalibration line](#read-the-recalibration-line)
- [Read the BUDGET STATS header](#read-the-budget-stats-header)
- [Respond to a WARNING](#respond-to-a-warning)
- [Start a new task mid-session](#start-a-new-task-mid-session)
- [Update the command](#update-the-command)
- [Debug common problems](#debug-common-problems)

---

## Install the command

**Prerequisites**: [Claude Code](https://claude.ai/code) CLI installed.

```bash
git clone git@github.com:bsommers/token-finops.git
cp token-finops/commands/token-ops.md ~/.claude/commands/token-ops.md
```

Verify it's picked up — in any Claude Code session:

```
/help
```

`/token-ops` should appear in the command list. No restart is required; commands are read from `~/.claude/commands/` per invocation.

---

## Invoke /token-ops

```
/token-ops <describe the task>
```

**Example:**

```
/token-ops add rate limiting middleware to the /api/upload endpoint and cover it with tests
```

If you invoke `/token-ops` with no task description, Claude will ask you what to scope before doing anything else — it will not guess.

---

## Read the forecast table

Before touching any files, Claude replies with a table like:

```
| Line item | Estimate | Basis |
|---|---|---|
| Initial baseline | ~25,000 tokens | fixed cost |
| File read cost | ~3,200 tokens | src/middleware/rateLimit.ts (140 lines), src/routes/upload.ts (90 lines), tests/upload.test.ts (110 lines) |
| Reasoning/thinking budget | ~8,000 tokens | moderate complexity — new middleware + tests |
| Output generation | ~6,000 tokens | new middleware file, route wiring, test file |
| **Total allocated task budget (Y0)** | **~42,200 tokens** | |

Allocated budget (Y0): ~42,200 tokens.
```

Check that the named files actually match what you expect the task to touch. If they don't, that's a signal Claude has misunderstood scope — better to correct it here than after work has started. Treat this number as provisional — it's a pre-discovery guess, refined next in Phase 1.5 once real scoping has happened.

---

## Read the recalibration line

If any planning or discovery happens before the first file gets written — you ran a GSD planning phase, a gstack plan-review skill, or Claude just read a few files to understand the existing pattern — Claude recalibrates the forecast once, right before that first `Write`/`Edit`, and reports it as a single delta line rather than a new table:

```
[RECALIBRATED BUDGET: Y0 → Y1 (Δ+21%) | basis: 4 files confirmed via Read/Grep (was 3 estimated)]
```

This works whether or not you're using a planning framework — see [FORECASTING.md](FORECASTING.md#worked-examples) for the mechanics with GSD, with gstack, and with neither. From this point on, `Y1` (not `Y0`) is the `Allocated` value in every `BUDGET STATS` line.

If the task was simple enough that no scoping happened before the first edit, you won't see this line at all — `Y0` just carries forward unchanged, silently. That's expected, not a bug.

If a recalibration delta comes back surprisingly large (say, +75% or more), that's worth pausing on — it usually means the task was significantly under-scoped in the original description, and it may be worth confirming plan/scope with the user before continuing rather than trusting the new number blindly.

---

## Read the BUDGET STATS header

From the next turn onward, every reply opens with one line before anything else:

```
[BUDGET STATS: Used approx: 18,400 / Allocated: 42,200 | Current Context Depth: 61,000 tokens | Status: ON-TRACK]
```

| Field | Meaning |
|---|---|
| `Used approx: X` | Running estimate of tokens spent on *this task* so far |
| `Allocated: Y` | The total from the Phase 1 forecast — fixed until you start a new task |
| `Current Context Depth: Z` | Estimate of the *whole conversation's* context size — can be larger than Y even when the task itself is on-track |
| `Status` | `ON-TRACK` while `X < 0.70 × Y`, otherwise `WARNING` |

Treat `Z` as the number to watch for overall session health, and `X`/`Y` as the number to watch for whether this specific task is running over its own plan.

---

## Respond to a WARNING

When `Status` flips to `WARNING`, Claude will, in that same turn:

1. Stop before starting any new tool calls or edits.
2. Write a state summary (what's done, what's left, key file paths, key decisions) to a file under the session's scratchpad directory.
3. Tell you the file path and ask you to run `/compact` or `/clear`.
4. Wait for your response rather than continuing on its own.

What to do:

```
# Option A — compact and keep going in the same session
/compact

# Option B — start clean, then point Claude at the summary file
/clear
# then, in the fresh session:
Resume from /path/to/scratchpad/summary.md
```

Prefer `/compact` for tasks you want to keep going on with as much prior context intact as possible; prefer `/clear` when the session has accumulated a lot of now-irrelevant context (e.g., several unrelated tasks before this one).

---

## Start a new task mid-session

If you give Claude a new, unrelated task after finishing (or abandoning) the current one, it treats it as a fresh Phase 1: `X` resets to zero and `Y0` is recomputed from a new forecast for the new task, with Phase 1.5 running again once that new task's planning is done. The old allocation isn't carried forward or blended in. If you want a fresh forecast without waiting for Claude to infer the task changed, just invoke `/token-ops <new task>` again explicitly.

---

## Update the command

```bash
cd token-finops
git pull origin main
cp commands/token-ops.md ~/.claude/commands/token-ops.md
```

To change the protocol itself (e.g. adjust the 70% threshold or the baseline estimate), edit `commands/token-ops.md` directly, then copy it to `~/.claude/commands/` and commit:

```bash
$EDITOR commands/token-ops.md
cp commands/token-ops.md ~/.claude/commands/token-ops.md
git add commands/token-ops.md
git commit -m "tune: adjust warning threshold to 80%"
git push
```

---

## Debug common problems

### `/token-ops` doesn't appear in `/help`

**Cause**: The file isn't at `~/.claude/commands/token-ops.md`, or wasn't copied after a repo update.
**Fix**:
```bash
ls ~/.claude/commands/token-ops.md   # must exist
diff ~/.claude/commands/token-ops.md token-finops/commands/token-ops.md  # should be empty
```

### Claude never prints `[BUDGET STATS: ...]` after the first task turn

**Cause**: The instruction to open every reply with the header can fall out of effective attention in a very long session, or the user started the task without invoking `/token-ops` at all (typed the task directly instead of `/token-ops <task>`).
**Fix**: Re-invoke `/token-ops` explicitly, or remind Claude directly: "resume the /token-ops BUDGET STATS header on every turn."

### The forecast table doesn't name any files

**Cause**: The task description was too vague for Claude to scope concrete files.
**Fix**: Per the command's own rules, Claude should ask a clarifying question rather than invent a number — if it didn't, prompt it: "which files does this actually touch?" and ask it to redo the forecast.

### Numbers in `BUDGET STATS` look obviously wrong (e.g., not moving turn to turn)

**Cause**: This is a self-reported heuristic estimate, not an instrumented count (see [ARCHITECTURE.md](ARCHITECTURE.md#known-limitations)) — it can drift.
**Fix**: Treat the absolute numbers as approximate; what matters is the trend and whether `Status` flips to `WARNING` at a reasonable point. If it's consistently far off, that's a signal to manually `/compact` earlier rather than waiting for the gate.
