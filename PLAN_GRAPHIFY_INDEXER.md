# Pending implementation plan: pluggable codebase indexers (graphify alternate)

> **Status: approved, not yet implemented.** Saved here (rather than only in the ephemeral Claude Code plan-mode file) so work can resume after a Claude Code restart/update without re-deriving the design. Once implemented, delete this file — its content becomes the commit history and the doc updates it describes.

## Context

`scripts/prerun_estimate.py` currently gets its only codebase-size signal from `scripts/index_repo.py`: a flat line count (`total_loc`), fed into `estimate_claude_security_cost()` as `LOC × 12.5 tokens`. That's a single number regardless of how the code is actually structured — a 5,000-LOC repo of simple, isolated CRUD handlers and a 5,000-LOC repo of deeply interconnected, cross-module event plumbing get an identical cost estimate today, even though the second one plausibly needs more agentic hops (higher step count) for a taint/exploit-hunt-depth scan to trace call chains across files.

The user already has `graphify` installed (`~/.claude/skills/graphify/`) and asked whether it — or other codebase-indexing mechanisms — could feed the estimator a better picture of "codebase size and complexity" than a raw LOC count. Graphify builds a knowledge graph of a codebase (nodes = symbols/files, edges = calls/imports/relationships, plus community detection and "god node" hub analysis) and persists it to `graphify-out/graph.json` + `graphify-out/GRAPH_REPORT.md`. That's a real, already-available structural-complexity signal this repo doesn't use today.

This plan makes the estimator's codebase-size input **pluggable**, with `index_repo.py` remaining the unconditional, zero-setup default, and a new graphify-backed indexer as an **opt-in** alternate for repos where a graph already exists.

**Hard constraint (per user's explicit answer):** `index_repo.py` (the "simple estimator") must remain fully available and the default — the user should never be forced into using graphify. The graphify indexer is purely an opt-in upgrade path for better estimates when a graph already exists, never a requirement.

**Hard constraint (per user's explicit answer):** the graphify indexer must never trigger a fresh `/graphify` build itself. Building a graph can cost real LLM tokens (semantic extraction) and sometimes a network call (Gemini) — that would break this whole toolchain's documented "offline, no network, no model calls" guarantee (see `docs/LOCAL_PRESCAN_INDEXING.md`). If no graph exists yet, the indexer fails clearly and tells the user to run `/graphify` first.

**Complexity signal (per user's explicit answer):** edge-to-node ratio — how interconnected the codebase is — is the single signal driving the cost multiplier. Simple, explainable, and a reasonable proxy for "how many cross-file hops would a scanning agent need."

## Design

### 1. Normalize the indexer output contract

Both indexers must return the same shape so `prerun_estimate.py` and `estimate_claude_security_cost()` don't need to know which one ran. Extend the dict `index_repo()` already returns (`scripts/index_repo.py:95-144`) with two new optional keys, defaulted so existing callers/tests see zero behavior change:

```python
{
    ...,               # existing keys unchanged: total_loc, files_counted, by_extension, etc.
    "source": "loc",    # or "graphify" — which backend produced this result
    "complexity": None, # or {"node_count": int, "edge_count": int, "edge_to_node_ratio": float, "multiplier": float}
}
```

`index_repo.py` itself just adds `"source": "loc", "complexity": None` to its existing return dict — one line, no behavior change.

### 2. New file: `scripts/graphify_indexer.py`

- Requires `<root>/graphify-out/graph.json` to exist. If missing, raise a clear error (`FileNotFoundError` with a message: `"No graphify graph found at <path>. Run /graphify <path> first, then re-run this indexer."`) — no silent fallback to `index_repo.py`, matching this repo's existing "never invent a number silently" posture (see `token-ops`'s own forecasting philosophy in `docs/FORECASTING.md`).
- Delegates `total_loc` and the file-count breakdown to `index_repo.index_repo()` unchanged (reuse, don't reimplement LOC counting) — this file's only job is to *add* the complexity signal, not replace LOC counting.
- Reads `graphify-out/graph.json`, counts `len(nodes)` and `len(edges)` (schema per `~/.claude/skills/graphify/references/extraction-spec.md` — top-level `nodes`/`edges` arrays), computes `edge_to_node_ratio = edge_count / node_count`.
- Computes `multiplier = clamp(edge_to_node_ratio / BASELINE_RATIO, 0.75, 2.0)`, where `BASELINE_RATIO` is a module-level constant (start at `1.5`, documented as a draft default — same "unverified, to be tuned" honesty as the existing `μ_steps` table in `SECURITY_SCAN_ESTIMATOR.md`). Clamping keeps a pathological graph from producing an absurd swing.
- Returns the same dict shape as `index_repo()`, with `"source": "graphify"` and `"complexity"` populated.

### 3. Extend `estimate_claude_security_cost()` (`scripts/estimate_claude_security_cost.py`)

Add an optional `complexity_multiplier: float = 1.0` parameter. Apply it only to the two terms that represent agentic traversal work — `cache_read_tokens` and `dynamic_input_tokens` — not `write_tokens` (loading the codebase once into cache isn't affected by how interconnected it is) and not the flat per-step `output` term. When the multiplier is `1.0` (the default, and always the case for the `loc` backend), output is byte-for-byte identical to today — this is strictly additive.

### 4. `scripts/prerun_estimate.py` changes

- New flag: `--indexer {loc,graphify}` (default `loc`).
- When `graphify` is selected, import and call `graphify_indexer.index_repo(...)` instead of `index_repo.index_repo(...)`; pass the result's `complexity["multiplier"]` through to `estimate_claude_security_cost()` for every profile row.
- Table output gains one line under the table (only when `source == "graphify"`) showing the multiplier and its inputs, e.g.:
  `Complexity: edge/node ratio 2.1 (from graphify-out/graph.json, 340 nodes / 714 edges) → 1.4x cost multiplier applied.`
  This keeps the number auditable rather than a silent adjustment — same transparency bar as the existing `Rate card and LOC-density factor are unverified defaults` footer line.
- If `--indexer graphify` is passed but no graph exists, let `graphify_indexer`'s error propagate with a clean message (no traceback), then exit non-zero.

### 5. Documentation

- `docs/LOCAL_PRESCAN_INDEXING.md`: add an "Alternate indexers" section documenting `loc` (default, zero-setup, offline) vs `graphify` (opt-in, requires a graph you already built, adds a structural-complexity multiplier) with a worked example table showing the same repo's estimate with and without the multiplier applied. State plainly: `loc` remains fully supported and the default — `graphify` is an upgrade path for better estimates when available, never a requirement.
- `docs/SECURITY_SCAN_ESTIMATOR.md`: update open question #1 ("Language/stack-specific token-per-LOC factor") to note that codebase-complexity weighting now has an optional, draft answer via the graphify path, still flagged unverified/to-be-tuned (the `BASELINE_RATIO` constant in particular).
- `README.md`: one line in the estimator's "What It Does"-equivalent section noting the optional `--indexer graphify` path exists, without disturbing the existing Mythos-5/Enterprise framing.

## Files touched

- `scripts/index_repo.py` — add two keys to the existing return dict (no logic changes)
- `scripts/graphify_indexer.py` — new file, ~60-80 lines
- `scripts/estimate_claude_security_cost.py` — add `complexity_multiplier` parameter, apply to two of four cost terms
- `scripts/prerun_estimate.py` — add `--indexer` flag, wire the alternate backend, print the multiplier line
- `docs/LOCAL_PRESCAN_INDEXING.md`, `docs/SECURITY_SCAN_ESTIMATOR.md`, `README.md` — doc updates described above

## Verification

- `python3 -c "import ast; [ast.parse(open(f).read(), f) for f in [...]]"` (existing sanity check, extended to include the new file)
- `python3 scripts/prerun_estimate.py --budget-usd 10` (default `loc` path) — output must be byte-identical to current behavior, proving the change is additive
- Build a real graph on this repo (`/graphify .`) as a one-time manual step, then `python3 scripts/prerun_estimate.py --indexer graphify --budget-usd 10` — confirm the complexity line prints, the multiplier is in `[0.75, 2.0]`, and costs scale sensibly relative to the `loc`-only run
- Test the error path: run `--indexer graphify` in a directory with no `graphify-out/` — confirm a clean, non-traceback error message

## Out of scope (explicitly, per this plan)

- Auto-invoking `/graphify` from the estimator (ruled out — breaks the offline/no-cost guarantee)
- Any other indexer backend (e.g. a language-aware AST complexity tool, cloc, tokei) — this plan only wires up graphify per the user's specific question; the same plug interface would make adding another backend later straightforward, but no other backend is implemented here
- Tuning `BASELINE_RATIO` or the clamp bounds against real scan data — flagged as draft, same as the existing unverified step-count multipliers

## How to resume after restart

1. Read this file.
2. Implement in the order listed under "Files touched" (indexer contract first, then the new graphify indexer, then the cost-function parameter, then the CLI wiring, then docs).
3. Run the verification steps above.
4. Delete this file once implemented and documented (its content will have moved into the code + `docs/LOCAL_PRESCAN_INDEXING.md`).
