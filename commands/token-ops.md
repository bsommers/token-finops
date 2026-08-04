Plan and monitor a token budget for the coding task in $ARGUMENTS. If $ARGUMENTS is empty, ask the user what task to scope before doing anything else.

This command has two phases: a one-time forecast before any work starts, then a running budget header on every subsequent turn for the rest of this session.

## Phase 1 — Token Budget Forecast (before any tool calls or code)

Before reading a single file or writing any code, analyze the task's complexity and output a forecast as a markdown table:

| Line item | Estimate | Basis |
|---|---|---|
| Initial baseline (system overhead + CLAUDE.md + tool schemas) | ~25,000 tokens | fixed cost, roughly constant per session |
| File read cost | [sum] | list every file you expect to read or grep, with its approximate line count, at ~5 tokens/line (~500 tokens per 100 lines) |
| Reasoning/thinking budget | [cap, e.g. 8,000] | scale with task complexity — trivial edits ~2,000, multi-file refactors ~8,000-15,000 |
| Output generation | [estimate] | approximate size of code + prose you expect to produce |
| **Total allocated task budget** | **[sum of the above]** | |

Rules for this table:
- Name the specific files you expect to touch (from a quick `ls`/`grep` pass if needed) rather than a vague guess — an unnamed estimate isn't a forecast.
- If the task is too vague to scope files, say so and ask a clarifying question before forecasting, rather than inventing a number.
- Keep the forecast itself short — the table plus at most two sentences of caveats. Don't write a design doc.

After the table, state the allocated total plainly, e.g. "Allocated budget: ~48,000 tokens." This is the Y value used in Phase 2.

## Phase 2 — Utilization Monitoring Protocol (every subsequent turn)

Starting with your very next response in this session, and on every turn thereafter until the task is done or the user ends monitoring, open your response with a single compact status line, before any other text:

`[BUDGET STATS: Used approx: X / Allocated: Y | Current Context Depth: Z tokens | Status: ON-TRACK / WARNING]`

Where:
- **X** = your running estimate of tokens consumed so far this task (baseline + cumulative file reads + cumulative thinking + cumulative output). Update it turn over turn — don't recompute from scratch or let it silently reset.
- **Y** = the total allocated budget from Phase 1, unchanged unless you explicitly re-forecast.
- **Z** = your estimate of current total context depth (everything in the conversation so far, including tool results), independent of the task budget — this can exceed Y even when the task itself is on-track, and is the number that matters for context-window health.
- **Status** = `WARNING` once X crosses 70% of Y, otherwise `ON-TRACK`.

You will not have exact token counts — estimate from observable signals: lines read, characters written, rough thinking effort spent. Bias toward slightly overestimating rather than under.

When Status flips to `WARNING`:
1. Pause before starting new tool calls or edits.
2. Write a concise state summary (what's done, what's left, key file paths and decisions) to a temp file under the scratchpad directory.
3. Tell the user the budget threshold was crossed, name the summary file, and prompt them to run `/compact` or `/clear` before continuing.
4. Wait for the user's direction rather than proceeding automatically.

If the user gives a new task mid-session, treat it as a new Phase 1 forecast (reset X, recompute Y) rather than silently folding it into the old budget.
