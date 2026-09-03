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

## Alternate indexers

`prerun_estimate.py` takes `--indexer {loc,graphify}`, choosing which backend supplies the codebase-size signal:

- **`loc` (default).** [`scripts/index_repo.py`](../scripts/index_repo.py), the LOC counter described above. Zero setup, fully offline, no dependency on anything else being installed or built. This remains fully supported and is what runs when `--indexer` is omitted — `graphify` is an upgrade path for a better estimate when available, never a requirement.
- **`graphify` (opt-in).** [`scripts/graphify_indexer.py`](../scripts/graphify_indexer.py) reuses `index_repo.py`'s LOC count unchanged, then adds a structural-complexity signal read from an already-built graphify knowledge graph (the `/graphify` skill's output) at `graphify-out/graph.json`: the ratio of edges to nodes, i.e. how interconnected the codebase is. A more interconnected codebase plausibly needs more agentic hops (cross-file traversal) for a taint/exploit-hunt-depth scan to trace call chains, so the ratio drives a bounded cost multiplier (`edge_to_node_ratio / 1.5`, clamped to `[0.75, 2.0]`) applied to the two cost terms that represent agentic traversal work (`cache_read_cost`, `dynamic_input_cost`) — not the flat cache-write or output terms.

This indexer **never builds or updates a graph itself.** Running `/graphify` can cost real LLM tokens (semantic extraction) and sometimes a network call, which would break the offline/no-model-calls guarantee above. If `graphify-out/graph.json` doesn't exist yet, `--indexer graphify` fails with a clear message telling you to run `/graphify <path>` first — there's no silent fallback to the `loc` backend.

Worked example: the same repo, `loc` vs `graphify` (a synthetic 100-node/210-edge graph, ratio 2.1, multiplier 1.4x):

```
# --indexer loc (default)
| standard_taint_audit | 150 | 3,286,617 | $38.69 | ❌ |

# --indexer graphify
| standard_taint_audit | 150 | 3,555,080 | $46.65 | ❌ |

Complexity: edge/node ratio 2.10 (from graphify-out/graph.json, 100 nodes / 210 edges) → 1.40x cost multiplier applied.
```

The `BASELINE_RATIO` constant (`1.5`) and the clamp bounds are draft defaults, unverified against a real scan — same honesty bar as the LOC-density factor below.

## Token sources: how the payload gets counted

`--indexer` decides how the repo's *structure* is measured. `--token-source` decides how its *token count* is arrived at — the number that actually drives the bill. Four options, in increasing order of accuracy and decreasing order of convenience:

| `--token-source` | Offline? | Accuracy | Needs |
|---|---|---|---|
| `loc` (default) | ✅ fully | heuristic — `LOC × 12.5` | nothing |
| `repomix` | code stays local¹ | measured payload size | `npx` / repomix |
| `gitingest` | code stays local¹ | measured payload size | gitingest |
| `count-tokens` | ❌ **sends your source to Anthropic** | **exact** | `anthropic` package + credentials |

¹ Neither packer transmits your code, but `npx -y repomix` does download the package on first use. Only `count-tokens` sends source code off the machine.

**Why the packers' own token counts are ignored.** Repomix and Gitingest both report a token estimate computed with **tiktoken, OpenAI's tokenizer**. That number is wrong for Claude — tiktoken undercounts Claude tokens by roughly 15–20% on prose and by more on code. This repo therefore uses those tools only as *packers* and derives the count itself from the packed payload, using Anthropic's published figure for the current tokenizer (**1M tokens ≈ 2.5M Unicode characters**). If you see a token count in repomix's own summary, do not budget against it.

**Why `loc` is still the default.** It needs nothing installed, makes no network call of any kind, and keeps the guarantee at the top of this document intact. It is a heuristic and is labelled as one in the output.

**The exact path.** `--token-source count-tokens` sends the packed source to Anthropic's `messages.count_tokens` endpoint, which is free to call and uses the real tokenizer for the model you name. It is the ground truth for both cost and context-window fit:

```bash
python3 scripts/prerun_estimate.py --token-source count-tokens --model claude-mythos-5-1
```

This **breaks the offline guarantee** — it is opt-in for exactly that reason, it prints a warning when it runs, and it never happens unless you ask for it. If you can't reach the model you're estimating (Mythos is Project Glasswing-limited), count with one you can: every model in the rate card shares the current tokenizer, so the count is identical.

```bash
python3 scripts/prerun_estimate.py --token-source count-tokens \
  --model claude-mythos-5-1 --count-tokens-model claude-opus-5
```

### Recommended workflow

1. Start with the default (`loc`) for a free, instant, offline ballpark.
2. If the number is near a budget boundary, re-run with `--token-source count-tokens` for the exact figure — the endpoint is free, so the only cost is the network round-trip and the privacy trade-off.
3. Gate on it: `--profile deep_exploit_hunt --budget-usd 250` exits **2** if that profile breaches the budget, so this can front a CI job or a pre-scan hook.

## Open questions / future work

- **Per-language token density.** `index_repo.py` already buckets LOC by extension — that's the natural place to apply a per-language `tokens/LOC` factor once [SECURITY_SCAN_ESTIMATOR.md](SECURITY_SCAN_ESTIMATOR.md)'s open question #1 is resolved, instead of the current flat `× 12.5` blended default across every extension.
- **No validation against a real scan yet.** The $\mu_{\text{steps}}$ multipliers and per-step token volumes in the estimation model are a generic agentic-scan shape, not measured from an actual `/claude-security` run. Worth checking a real scan's `/workflows` detail or `/cost` output against what `prerun_estimate.py` predicted for the same repo/scope, and correcting the multipliers from that delta.
- **Command-ifying this.** Right now this is two scripts run by hand. If the workflow proves useful, it's a natural fit for a `/token-ops`-style command file — a "Phase 0" forecast step that runs before `/claude-security scan codebase` is invoked, the same way `/token-ops` Phase 1 runs before any code gets written.
