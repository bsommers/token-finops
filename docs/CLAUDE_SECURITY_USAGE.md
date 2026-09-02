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

**This repo's dollar estimator (`prerun_estimate.py`) targets the managed product**, not the plugin — because the managed product is the one with a fixed model (Claude Mythos 5) and direct per-token billing, a dollar figure computed for it is actually invoice-comparable. The plugin has neither: it runs on whatever model your Claude Code account has access to, and its cost isn't billed separately at all — it just draws down your Claude Code plan's usage limits, the same pool `/token-ops` already forecasts and monitors. So for a plugin run, use `/token-ops` (token/context budget, same session) rather than this estimator's dollar figure, which wouldn't correspond to anything on an actual bill. This also resolves one of [SECURITY_SCAN_ESTIMATOR.md](SECURITY_SCAN_ESTIMATOR.md)'s open questions: the answer to "what integration surface" is *both*, but only the managed product is the one this repo puts a dollar figure on.

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

For the **managed product**, there's no pre-flight step at all today — you commit to a scan without seeing a number first. This repo's estimator fills that gap directly: run it against the repo (or the same GitHub repo/scope you'd point `claude.ai/security` at) to get an actual $ figure, on the same fixed model and billing basis the managed product actually uses, before you kick off a scan there.

The **plugin** already does a lightweight pre-flight of its own: "The plugin reads your repository first, then offers the whole repository or a focused area, with each option's **file count and relative cost** stated." That's qualitative — no dollar figure, no token count — and this repo's estimator can still be run alongside it as a rough sanity check (see the correspondence table below), but its dollar output isn't the plugin's real cost, since the plugin has no fixed model or per-token bill of its own:

```bash
# 1. Index the repo locally (offline, no network, no model calls)
python3 scripts/index_repo.py --scope path/to/area   # omit --scope for the whole repo

# 2. Get a cost table across scan-depth profiles, flagged against a budget
python3 scripts/prerun_estimate.py --scope path/to/area --budget-usd 25
```

Worked example, run against this repo itself:

```
$ python3 scripts/prerun_estimate.py --budget-usd 5
Indexed 13 files (1 excluded) via git ls-files under scope '.': 1,512 LOC

| Profile | Steps | Est. total tokens | Est. cost (USD) | Fits budget? |
|---|---|---|---|---|
| pr_quick_scan | 10 | 124,602 | $1.85 | ✅ |
| standard_taint_audit | 150 | 3,223,785 | $38.59 | ❌ |
| deep_exploit_hunt | 500 | 18,325,359 | $229.24 | ❌ |
```

### Rough correspondence to the plugin's own jobs

Neither the plugin nor the managed product exposes "profiles" — each sizes a run to whatever scope you pick, and the actual step count is Claude's own agentic behavior, not a config value. Treat this table as a loose mapping only, useful for picking which row to sanity-check a real run against (a plugin run's actual cost still comes out of your Claude Code plan's usage limits, not this table's dollar figure):

| This repo's profile | Roughly corresponds to |
|---|---|
| `pr_quick_scan` | Plugin's **Scan changes** job (branch diff / single PR / single commit) |
| `standard_taint_audit` | Plugin's **Scan codebase**, scoped to a focused area (e.g. "your auth code") |
| `deep_exploit_hunt` | Plugin's **Scan codebase** over a large, unscoped repository |

## Why the billing-model difference matters here

Because the plugin's cost is drawn from your **Claude Code plan's usage limits**, not billed separately, a large `/claude-security` scan run mid-session behaves exactly like any other token-heavy turn `/token-ops` already forecasts and monitors — it's the same pool. If you're running both in one session: use `/token-ops` for the session-level running total, and `prerun_estimate.py` beforehand for the scan-specific go/no-go decision, since the scan's own token draw can dwarf ordinary coding-task usage (see the table above — a `deep_exploit_hunt`-sized scan is a very different budget event than a file edit).

For the managed product, billing is a separate, direct-token-cost line item — the estimator's dollar figures there are directly comparable to an actual invoice, using the confirmed Claude Mythos 5 rate card (see [SECURITY_SCAN_ESTIMATOR.md](SECURITY_SCAN_ESTIMATOR.md#config--rate-card)).

## One documented gotcha

> "Fable 5.1's safeguards flagged this message" / "Fable 5's safeguards flagged this message" — Fable's cybersecurity safety classifiers block certain scan activities and the run auto-downgrades to Opus. Expected; the scan still completes.

## What's now verified vs. still open

- **Rate card and model ID — resolved.** [`schemas/claude_security_pre_run_estimator.json`](../schemas/claude_security_pre_run_estimator.json) now carries a single entry, `claude-mythos-5` (the confirmed API model ID for the managed product's scan model), with per-token rates taken directly from [Anthropic's published pricing page](https://platform.claude.com/docs/en/about-claude/pricing): $10/MTok input, $50/MTok output, $1/MTok cache read, $20/MTok 1h cache write, 50% batch discount. The earlier `claude-opus-4.7` entry was removed — it never corresponded to a real billing surface here, since the plugin (the only place that model choice would matter) doesn't use a fixed rate card at all.
- **Actual step counts / token volumes for a real scan — still open.** Nothing published gives real numbers here; the $\mu_{\text{steps}}$ multipliers in `SECURITY_SCAN_ESTIMATOR.md` are a generic agentic-scan model, not measured from an actual scan. Worth validating a managed-product scan's actual billed usage (from its invoice) against what `prerun_estimate.py` predicted for the same repo/scope, and correcting the multipliers from that delta.
- The plugin's own file-count-based sizing already accounts for things this estimator can't see (e.g. how "focused" a chosen area actually is) — for plugin runs, treat `prerun_estimate.py`'s numbers as a loose sanity check only, not a substitute for what the plugin reports at its own confirm step or a real dollar figure.
