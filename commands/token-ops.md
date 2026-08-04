Plan and monitor a token budget for the coding task in $ARGUMENTS. If $ARGUMENTS is empty, ask the user what task to scope before doing anything else.

This command has three phases: an initial rough forecast before any work starts, an optional recalibration once planning/scoping is done and before the first build action, and a running budget header on every subsequent turn for the rest of this session. Full calculation methodology and worked examples live in [FORECASTING.md](../FORECASTING.md) — this file is the operative contract; that doc is the reference for *why* the numbers are what they are.

## Phase 1 — Initial Forecast (before any tool calls or code)

Before reading a single file or writing any code, analyze the task's complexity and output a forecast as a markdown table:

| Line item | Estimate | Basis |
|---|---|---|
| Initial baseline (harness + tool schemas + CLAUDE.md + skill/agent listings) | ~25,000 tokens | fixed cost, roughly constant per session — see baseline breakdown below |
| File read cost | [sum] | list every file you expect to read or grep, with its approximate line count, at ~5 tokens/line (~500 tokens per 100 lines) |
| Reasoning/thinking budget | [pick a tier below] | scale with decision complexity, not just file count |
| Output generation | [estimate] | approximate size of code/diff + prose you expect to produce, same ~5 tokens/line basis for code |
| **Total allocated task budget (Y0)** | **[sum of the above]** | |

**Baseline breakdown** (why ~25,000, and when to adjust it): this is harness system prompt + currently-loaded tool schemas + CLAUDE.md files (global and project) + the skill/agent/command name+description listings surfaced for routing. ~25,000 is a reasonable default for a typical setup. If the project has an unusually large CLAUDE.md, many MCP servers, or a large installed skill catalog, increase it — a quick proxy is (CLAUDE.md line count × ~5 tokens/line) added on top of an ~18,000 token floor for harness + tools.

**Reasoning/thinking budget tiers** — pick the tier matching the task, don't default to the middle:

| Tier | Signal | Budget |
|---|---|---|
| Trivial | single file, single well-defined change, no ambiguity | ~1,000–2,000 |
| Simple | 1–3 files, follows an established pattern already in the codebase | ~2,000–4,000 |
| Moderate | multiple files, some design decisions, new code paths | ~4,000–8,000 |
| Complex | cross-cutting change, multiple subsystems, non-obvious trade-offs | ~8,000–15,000 |
| Very complex / research-heavy | unknown unknowns — requires exploration before design is even possible | ~15,000–30,000+ |

Rules for the Phase 1 table:
- Name the specific files you expect to touch (from a quick `ls`/`grep` pass if needed) rather than a vague guess — an unnamed estimate isn't a forecast.
- If the task is too vague to scope files, say so and ask a clarifying question before forecasting, rather than inventing a number.
- Keep the forecast itself short — the table plus at most two sentences of caveats. Don't write a design doc.

After the table, state the allocated total plainly, e.g. "Allocated budget (Y0): ~48,000 tokens." Treat Y0 as provisional — it's a pre-discovery estimate and is expected to be revised in Phase 1.5 once real information exists.

## Phase 1.5 — Plan-Informed Recalibration (before the first build action)

Trigger this once, on the turn immediately before your first deliverable-producing action (`Write`, `Edit`, `NotebookEdit`, or equivalent code-generation/apply-patch step) — provided at least one scoping/discovery action has already happened in this task (a `Read`, `Glob`, `Grep`, `ls`, an Explore/Plan subagent, or a planning skill/command). This makes recalibration opportunistic, not framework-dependent: it fires the same way whether the discovery came from a structured planning package or from your own ad hoc file reads.

Pull in whichever of these signals actually exist in this session — use richer sources when present, fall back gracefully when they don't:
- **Structured plan artifacts, if present** — e.g. a GSD `PLAN.md`/`SPEC.md` under `.planning/`, a gstack plan-review output (`/plan-eng-review`, `/plan-ceo-review`, `/plan-design-review`), or any other planning package's task breakdown. If one exists, sum a per-step estimate from its actual task list instead of one blended guess.
- **A task list, if one exists** — e.g. `TodoWrite`/`TaskCreate` items created during planning. Use the item count and description detail as a complexity signal.
- **Nothing structured** — no framework, no task list, just files you opened while scoping. Use the real files and real line counts you now have from Phase 1's discovery pass. This path always works, with or without GSD, gstack, or any other package installed.

Recalculate using the same method as Phase 1, but with real numbers in place of guesses:
1. Replace estimated file line counts with actual ones (from what you've now read, or `wc -l`).
2. If a plan/task list exists, sum per-task cost rather than one lump estimate.
3. Re-pick the reasoning-budget tier — planning often reveals the task is simpler or more complex than the initial guess.
4. Re-estimate output generation now that the shape of the change (new files vs. edits, approximate diff size) is actually known.

Report the result as one compact delta line, not a new table:

`[RECALIBRATED BUDGET: Y0 → Y1 (Δ+18%) | basis: 6 files confirmed (was 4 estimated), complexity revised moderate→complex]`

From this point forward, **Y1 replaces Y0** as the `Allocated` value used in Phase 2. Carry forward the tokens already spent during Phase 1/1.5 discovery as part of `X` — don't reset it to zero just because Y changed.

If no discovery happened before the first build action (task was trivial enough to skip scoping), skip Phase 1.5 entirely and carry Y0 forward unchanged — recalibration is an enrichment step, never a blocking requirement.

## Phase 2 — Utilization Monitoring Protocol (every subsequent turn)

Starting with your very next response in this session, and on every turn thereafter until the task is done or the user ends monitoring, open your response with a single compact status line, before any other text:

`[BUDGET STATS: Used approx: X / Allocated: Y | Current Context Depth: Z tokens | Status: ON-TRACK / WARNING]`

Where:
- **X** = your running estimate of tokens consumed so far this task (baseline + cumulative file reads + cumulative thinking + cumulative output). Update it turn over turn — don't recompute from scratch or let it silently reset.
- **Y** = the current allocated budget — Y0 from Phase 1, or Y1 from Phase 1.5 if recalibration occurred. Unchanged after that unless you explicitly re-forecast.
- **Z** = your estimate of current total context depth (everything in the conversation so far, including tool results), independent of the task budget — this can exceed Y even when the task itself is on-track, and is the number that matters for context-window health.
- **Status** = `WARNING` once X crosses 70% of Y, otherwise `ON-TRACK`.

You will not have exact token counts — estimate from observable signals: lines read, characters written, rough thinking effort spent. Bias toward slightly overestimating rather than under.

When Status flips to `WARNING`:
1. Pause before starting new tool calls or edits.
2. Write a concise state summary (what's done, what's left, key file paths and decisions) to a temp file under the scratchpad directory.
3. Tell the user the budget threshold was crossed, name the summary file, and prompt them to run `/compact` or `/clear` before continuing.
4. Wait for the user's direction rather than proceeding automatically.

If the user gives a new task mid-session, treat it as a new Phase 1 forecast (reset X, recompute Y0, and go through Phase 1.5 again once that task's planning is done) rather than silently folding it into the old budget.
