# Using token-finops with Claude Security (Public Beta)

This doc maps this repo's draft cost estimator ([SECURITY_SCAN_ESTIMATOR.md](SECURITY_SCAN_ESTIMATOR.md)) onto the real Claude Security public beta, based on Anthropic's published docs as of 2026-09-02:
- [support.claude.com — Use Claude Security](https://support.claude.com/en/articles/14661296-use-claude-security)
- [claude.com/product/claude-security](https://claude.com/product/claude-security)
- [code.claude.com/docs/en/claude-security](https://code.claude.com/docs/en/claude-security)

## There are two different "Claude Security"s

| | **Claude Security** (managed) | **Claude Security plugin** (Claude Code) |
|---|---|---|
| Where it runs | `claude.ai/security`, hosted | Inside a Claude Code session, locally |
| Plan | Enterprise only | Any paid plan with [dynamic workflows](https://code.claude.com/docs/en/workflows) enabled |
| Model | Claude Mythos 5, fixed | Whichever model(s) you have access to in Claude Code |
| Repos | GitHub.com / GitHub Enterprise Server only | Any repo reachable from your machine, including GitLab/Bitbucket and no-inbound-network setups |
| Billing | "Charged at direct token cost only. There is no additional platform fee." | Counts against your **Claude Code plan's usage limits** — same budget `/token-ops` already tracks |
| CLI/API | None documented | `/claude-security` slash command |

**This repo's tooling targets the plugin**, not the managed product — it's the one that runs inside Claude Code, so it shares a session with `/token-ops` and can be pre-flighted locally the same way. This also resolves one of [SECURITY_SCAN_ESTIMATOR.md](SECURITY_SCAN_ESTIMATOR.md)'s open questions: the answer to "what integration surface" is *both*, but the plugin is the actionable one for this repo.

## Installing and invoking the plugin

```
/plugin install claude-security@claude-plugins-official
```

If Claude Code reports `Run /reload-plugins to activate.`, run:

```
/reload-plugins
```

Then in any session:

```
/claude-security
```

opens a menu with three jobs: **Scan codebase**, **Scan changes** (a branch diff, a PR, or a single commit — needs `git`), and **Suggest patches**. Findings land in a timestamped `CLAUDE-SECURITY-<timestamp>/` directory (`RESULTS.md`, `RESULTS.jsonl`, `RESULTS.sarif`, a revision stamp) with its own `.gitignore` so a stray `git add` never sweeps it into a commit. Patches are written to that directory's `patches/` folder and are **never applied automatically** — you `git apply` them yourself.

Prerequisites: a paid plan with dynamic workflows on (`/config` on Pro), `python3` 3.9+ on `PATH`, and `git` for change scans (a full scan works without version control).

## Where this repo's estimator fits

The plugin already does a lightweight pre-flight itself: "The plugin reads your repository first, then offers the whole repository or a focused area, with each option's **file count and relative cost** stated." That's qualitative — no dollar figure, no token count. This repo's estimator turns that into a number *before* you get to the plugin's confirm step:

```bash
# 1. Index the repo locally (offline, no network, no model calls)
python3 scripts/index_repo.py --scope path/to/area   # omit --scope for the whole repo

# 2. Get a cost table across scan-depth profiles, flagged against a budget
python3 scripts/prerun_estimate.py --scope path/to/area --budget-usd 25
```

Worked example, run against this repo itself:

```
$ python3 scripts/prerun_estimate.py --budget-usd 5
Indexed 13 files (1 excluded) via git ls-files under scope '.': 1,488 LOC

| Profile | Steps | Est. total tokens | Est. cost (USD) | Fits budget? |
|---|---|---|---|---|
| pr_quick_scan | 10 | 124,085 | $1.83 | ✅ |
| standard_taint_audit | 150 | 3,213,090 | $38.09 | ❌ |
| deep_exploit_hunt | 500 | 18,264,639 | $226.36 | ❌ |
```

### Rough correspondence to the plugin's own jobs

The plugin doesn't expose "profiles" — it sizes each run to whatever scope you pick, and its actual step count is Claude's own agentic behavior, not a config value. Treat this as a loose mapping only, useful for picking which row of the table to sanity-check against:

| This repo's profile | Roughly corresponds to |
|---|---|
| `pr_quick_scan` | Plugin's **Scan changes** job (branch diff / single PR / single commit) |
| `standard_taint_audit` | Plugin's **Scan codebase**, scoped to a focused area (e.g. "your auth code") |
| `deep_exploit_hunt` | Plugin's **Scan codebase** over a large, unscoped repository |

## Why the billing-model difference matters here

Because the plugin's cost is drawn from your **Claude Code plan's usage limits**, not billed separately, a large `/claude-security` scan run mid-session behaves exactly like any other token-heavy turn `/token-ops` already forecasts and monitors — it's the same pool. If you're running both in one session: use `/token-ops` for the session-level running total, and `prerun_estimate.py` beforehand for the scan-specific go/no-go decision, since the scan's own token draw can dwarf ordinary coding-task usage (see the table above — a `deep_exploit_hunt`-sized scan is a very different budget event than a file edit).

For the managed product, billing is a separate, direct-token-cost line item — the estimator's dollar figures there are more directly comparable to an actual invoice, modulo the rate-card caveat below.

## One documented gotcha

> "Fable 5.1's safeguards flagged this message" / "Fable 5's safeguards flagged this message" — Fable's cybersecurity safety classifiers block certain scan activities and the run auto-downgrades to Opus. Expected; the scan still completes.

## What's still unverified

- **Rate card and model IDs** in [`schemas/claude_security_pre_run_estimator.json`](../schemas/claude_security_pre_run_estimator.json): `claude-mythos-5.1` maps to a real model (Claude Mythos 5, confirmed as the managed product's scan model above), but the `.1` and the exact per-token rates aren't confirmed against live pricing. `claude-opus-4.7` doesn't match this account's current model lineup — the plugin doesn't use a fixed model at all, it uses whatever's available in your Claude Code account, so a fixed rate card doesn't really apply to plugin runs; use your account's normal per-token rates instead.
- **Actual step counts / token volumes for a real scan** — nothing published gives real numbers here; the $\mu_{\text{steps}}$ multipliers in `SECURITY_SCAN_ESTIMATOR.md` are a generic agentic-scan model, not measured from an actual `/claude-security` run. Worth validating against `/workflows` output or `/cost` during a real scan.
- The plugin's own file-count-based sizing already accounts for things this estimator can't see (e.g. how "focused" a chosen area actually is) — treat `prerun_estimate.py`'s numbers as a budget sanity check, not a substitute for what the plugin reports at its own confirm step.
