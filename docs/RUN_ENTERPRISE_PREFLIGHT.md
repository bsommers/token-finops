# Running a Pre-Flight Scan Estimate for the Claude Security Enterprise Service

Step-by-step: how to get a dollar figure for a scan on the **managed Claude Security product** (`claude.ai/security`, Enterprise-only, fixed on **Claude Mythos 5**, billed at direct token cost) *before* you run it — using this repo's tooling. See [CLAUDE_SECURITY_USAGE.md](CLAUDE_SECURITY_USAGE.md) for why this is the surface a dollar estimate is actually meaningful for, and [SECURITY_SCAN_ESTIMATOR.md](SECURITY_SCAN_ESTIMATOR.md) for the underlying cost model.

## 1. Point the indexer at the repo you're about to scan

The managed product only scans GitHub.com / GitHub Enterprise Server repos — index that same repo locally (offline, no network calls, no model calls):

```bash
cd /path/to/target-repo
python3 /path/to/token-finops/scripts/prerun_estimate.py --budget-usd 25
```

- Default `--root` is the current directory — run it from inside the target repo, or pass `--root /path/to/target-repo`.
- Add `--scope <subdir>` to restrict to a subdirectory if you're only scanning part of the repo (also narrows the real scan's cost, not just the estimate).
- `--model claude-mythos-5` is already the default — no need to pass it; it's the only entry in the rate card, since it's the only fixed-model, direct-billed surface this estimator targets.
- `--batch` applies the batch-API discount — not applicable to an interactive `claude.ai/security` run, only relevant if you're routing scans through a batch job.

## 2. Read the table

```
| Profile | Steps | Est. total tokens | Est. cost (USD) | Fits budget? |
|---|---|---|---|---|
| pr_quick_scan | 10 | ... | $X.XX | ✅/❌ |
| standard_taint_audit | 150 | ... | $X.XX | ✅/❌ |
| deep_exploit_hunt | 500 | ... | $X.XX | ✅/❌ |
```

Match the row to what you're actually about to run on the managed product:

| Profile | Roughly corresponds to |
|---|---|
| `pr_quick_scan` | A single branch/PR/commit diff |
| `standard_taint_audit` | A focused-area codebase scan |
| `deep_exploit_hunt` | A full, unscoped repository scan |

## 3. If LOC exceeds 500,000

`prerun_estimate.py` prints a warning naming the largest top-level directory. Scope to a subfolder with `--scope` — both for a tighter estimate here and because that's the same scoping decision that lowers the real scan's cost on `claude.ai/security`.

## 4. Run the actual scan

Take the number from step 2 as your go/no-go budget check, then run the scan at `claude.ai/security` (Enterprise plan required). This tool never calls the managed product itself — it's a local, offline pre-flight only.

## Caveat

The dollar figure uses the confirmed Claude Mythos 5 rate card (see [CLAUDE_SECURITY_USAGE.md](CLAUDE_SECURITY_USAGE.md)), but the *step-count* multipliers behind each profile (10 / 150 / 500) are still a generic agentic-scan model, not measured from a real `claude.ai/security` run. Treat the result as a budget sanity check, not gospel, until validated against an actual invoice — see the open questions in [SECURITY_SCAN_ESTIMATOR.md](SECURITY_SCAN_ESTIMATOR.md#open-questions-to-refine-later).
