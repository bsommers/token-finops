# Local Pre-Scan Indexing (Draft / Exploration)

The question this explores: **can something running locally, before code ever reaches Claude Security, cut down the tokens the scan itself consumes, and produce a token/cost estimate ahead of time?** Two different things get conflated in that question, so this doc answers them separately. See [CLAUDE_SECURITY_USAGE.md](CLAUDE_SECURITY_USAGE.md) for how this plugs into the actual Claude Security public beta.

## What runs locally

[`scripts/index_repo.py`](../scripts/index_repo.py) — fully offline, Python standard library only (no `pip install`, matching the Claude Security plugin's own "nothing installed" convention), no network calls, no model calls of any kind. It:

1. Lists files via `git ls-files` when run inside a git repo (so `.gitignore` is respected automatically), or falls back to `os.walk` with a conservative exclude list otherwise.
2. Filters to source-code-shaped extensions (`SOURCE_EXTENSIONS` in the script) and drops known noise even when `.gitignore` doesn't catch it: `node_modules/`, `vendor/`, `dist/`, `build/`, lockfiles, `.min.js`/`.min.css`, `__pycache__/`, `.terraform/`, and similar.
3. Counts lines per file, then aggregates by extension and by top-level directory, and lists the largest individual files.

```bash
python3 scripts/index_repo.py --scope services/auth --top 10
```

returns JSON: total LOC, files counted vs. excluded, a per-extension breakdown, a per-directory breakdown, and the largest files by line count.

## Does this cut tokens in the scan itself?

Be precise about what it does and doesn't do:

**It does not modify what Claude Security reads.** The plugin decides its own scope from what you pick in its `/claude-security` menu, and its architecture-mapping pass runs regardless of anything this script produces. There's no hook where `index_repo.py`'s output filters the plugin's file access — it's advisory, not enforced.

**What it does let you do, which does reduce tokens spent:**

1. **Point the scope at where the LOC actually is.** The plugin's own menu states file counts and a *relative* cost per option, but doesn't say which subdirectory is actually driving that cost. `index_repo.py --top 10` and its per-top-dir breakdown answer that directly — pick the scope that excludes the directories not worth the spend.
2. **Catch vendored/generated volume the plugin would otherwise walk.** If a repo's `.gitignore` is incomplete (a common state — generated protobuf output, a committed `vendor/` snapshot, etc.), a chunk of what looks like "your codebase" is actually not code worth an adversarial vulnerability hunt. Scoping the scan away from a directory the indexer flags as low-signal, high-LOC directly reduces the plugin's own token draw for that run.
3. **Turn a budget decision into a number before confirming.** Pairing the indexer with [`scripts/prerun_estimate.py`](../scripts/prerun_estimate.py) (below) and the guardrails in [SECURITY_SCAN_ESTIMATOR.md](SECURITY_SCAN_ESTIMATOR.md) (the 500k-LOC directory-scoping threshold, a hard `--budget-usd` cap) means the scoping decision happens *before* the plugin's "confirm the run" step, not after a scan is already burning tokens.

So: **indirectly, through better scoping decisions** — this is a decision-support tool, not a filter in the scan's data path.

## Getting an estimate before handoff

[`scripts/prerun_estimate.py`](../scripts/prerun_estimate.py) chains the indexer into [`estimate_claude_security_cost()`](../scripts/estimate_claude_security_cost.py) across all three scan-depth profiles and prints a markdown table:

```bash
python3 scripts/prerun_estimate.py --budget-usd 25 --model claude-mythos-5
```

Worked example, run against this repo's own root (`--scope services/auth` would restrict indexing to that subdirectory the same way, for a repo that has one):

```
Indexed 13 files (1 excluded) via git ls-files under scope '.': 1,512 LOC

| Profile | Steps | Est. total tokens | Est. cost (USD) | Fits budget? |
|---|---|---|---|---|
| pr_quick_scan | 10 | 124,602 | $1.85 | ✅ |
| standard_taint_audit | 150 | 3,223,785 | $38.59 | ❌ |
| deep_exploit_hunt | 500 | 18,325,359 | $229.24 | ❌ |
```

Add `--budget-usd` to get a ✅/❌ column per profile instead of just raw numbers, or `--batch` to apply the batch-API discount from the rate card.

## Open questions / future work

- **Per-language token density.** `index_repo.py` already buckets LOC by extension — that's the natural place to apply a per-language `tokens/LOC` factor once [SECURITY_SCAN_ESTIMATOR.md](SECURITY_SCAN_ESTIMATOR.md)'s open question #1 is resolved, instead of the current flat `× 12.5` blended default across every extension.
- **No validation against a real scan yet.** The $\mu_{\text{steps}}$ multipliers and per-step token volumes in the estimation model are a generic agentic-scan shape, not measured from an actual `/claude-security` run. Worth checking a real scan's `/workflows` detail or `/cost` output against what `prerun_estimate.py` predicted for the same repo/scope, and correcting the multipliers from that delta.
- **Command-ifying this.** Right now this is two scripts run by hand. If the workflow proves useful, it's a natural fit for a `/token-ops`-style command file — a "Phase 0" forecast step that runs before `/claude-security scan codebase` is invoked, the same way `/token-ops` Phase 1 runs before any code gets written.
