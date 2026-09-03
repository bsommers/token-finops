# Claude Security Pre-Run Cost Estimator (Draft)

**Value-add**: the Claude Security plugin's own pre-flight step only states a scan's cost *qualitatively* (file count + "relative cost"). This model puts an actual dollar figure on it, per scan-depth profile, before you confirm a run.

> **Status: draft, pending refinement.** This is a *pre-execution* cost estimator for agentic security-scan workloads (e.g. Claude Security-style multi-stage scans: indexing → call-graph traversal → dynamic tool calls → patch generation) — not the same thing as `/token-ops`. `/token-ops` forecasts and monitors a **live coding session's** token budget turn by turn; this estimator predicts the **dollar cost of a scan job before it runs**, from static inputs (lines of code, scan depth) alone, so it can gate whether the job runs at all. See [FORECASTING.md](FORECASTING.md) for the session-monitoring methodology this complements.

Open items below are intentionally left as TODOs — this doc captures the model as received, to be tuned once those are resolved. **See also**: [CLAUDE_SECURITY_USAGE.md](CLAUDE_SECURITY_USAGE.md) maps this model onto the real Claude Security public beta (managed product + Claude Code plugin), and [LOCAL_PRESCAN_INDEXING.md](LOCAL_PRESCAN_INDEXING.md) covers a local, offline indexer ([`scripts/index_repo.py`](../scripts/index_repo.py)) that feeds real LOC/directory data into the estimator below instead of a guessed total.

---

## Why a separate model from `/token-ops`

`/token-ops` estimates cost turn-by-turn *during* a session Claude is already running, from observable signals (files read, output produced). A security-scan pre-run estimator needs a different shape: it must produce a single dollar estimate *before* the scan starts, from just two static inputs — repo size (LOC) and a chosen scan-depth profile — so a budget gate can block or allow the job. That means separating:

- **Static codebase corpus volume** — how many tokens the codebase itself costs to load into the cache once.
- **Agentic execution multipliers** — how many times that cached context gets re-read, and how much fresh tool/reasoning output gets generated, as scan depth increases.

## Mathematical Estimation Model

$$\text{Total Cost} = C_{\text{write}} + C_{\text{read}} + C_{\text{uncached\_input}} + C_{\text{output}}$$

### 1. Baseline Token Conversion

- **Code token density**: $T_{\text{code}} \approx \text{LOC} \times 12.5$ tokens.
- **AST & symbol graph overhead**: $T_{\text{overhead}} \approx T_{\text{code}} \times 0.15$ (file tree, imports, dependencies, schema context).
- **Initial cache write** ($T_{\text{write}}$): $T_{\text{code}} + T_{\text{overhead}}$.

### 2. Agentic Multipliers by Scan Depth ($\mu$)

Agent step volume determines prompt-cache read volume:

| Scan profile | Iterations | $\mu_{\text{steps}}$ |
|---|---|---|
| Diff / PR scope | 5–15 | 10 |
| Standard taint / architecture audit | 100–250 | 150 |
| Deep zero-day / multi-pass exploit hunt | 400–800 | 500 |

### 3. Token Breakdown Formulas

- **Cache writes**: $T_{\text{write}}$
- **Cache reads**: $T_{\text{write}} \times \mu_{\text{steps}} \times \eta_{\text{cache\_scope}}$, where $\eta_{\text{cache\_scope}}$ is the average proportion of the codebase retained in active context per step (typically 0.15–0.30).
- **Dynamic input** (tool outputs/logs): $\mu_{\text{steps}} \times 15{,}000$ tokens.
- **Output** (reasoning & PoC): $\mu_{\text{steps}} \times 1{,}500$ tokens (or $3{,}000$ for deep verification/patch generation).

---

## Config / Rate Card

Machine-readable schema: [`schemas/claude_security_pre_run_estimator.json`](../schemas/claude_security_pre_run_estimator.json).

> ✅ **Rate card confirmed.** The estimator targets the **managed** Claude Security product (`claude.ai/security`, Enterprise-only), which Anthropic's docs confirm runs scans exclusively on **Claude Mythos 5** (API model ID `claude-mythos-5`) and is "charged at direct token cost only" — no additional platform fee. That combination — one fixed model, direct per-token billing — is what makes a dollar figure meaningful here at all. The rate card values ($10/MTok input, $50/MTok output, $1/MTok cache read, $20/MTok 1h cache write) are taken directly from [Anthropic's published pricing page](https://platform.claude.com/docs/en/about-claude/pricing), retrieved 2026-09-02. There is deliberately only one entry: the separate **Claude Security plugin for Claude Code** (`/claude-security` command) uses whichever model(s) you already have access to in your account, not a fixed scan model, and isn't billed separately at all — it draws from your Claude Code plan's usage limits instead, so a fixed rate card doesn't apply to it. See [CLAUDE_SECURITY_USAGE.md](CLAUDE_SECURITY_USAGE.md) for the full managed-vs-plugin breakdown.

## Executable Estimator

Reference implementation: [`scripts/estimate_claude_security_cost.py`](../scripts/estimate_claude_security_cost.py) — `estimate_claude_security_cost(loc, profile, model, is_batch)`, returns estimated total USD plus a cost and token-volume breakdown. Rather than guessing `loc`, feed it a real count from [`scripts/index_repo.py`](../scripts/index_repo.py), or run the two chained via [`scripts/prerun_estimate.py`](../scripts/prerun_estimate.py) for a one-shot table across all three profiles — see [LOCAL_PRESCAN_INDEXING.md](LOCAL_PRESCAN_INDEXING.md).

## Guardrails to Implement Before a Scan Runs

- **Hard-cap budget gating**: intercept jobs where `estimated_total_usd > budget_threshold` before triggering the scan — `prerun_estimate.py --budget-usd N` implements this as a ✅/❌ flag per profile.
- **Directory scoping**: if `loc > 500,000`, prompt for scoping to a sub-folder (e.g. `/services/auth/`) rather than scanning the whole repo root — `prerun_estimate.py` warns and names the largest top-level directory once this threshold is crossed.
- **Batch routing**: route full-repository scheduled/scanning audits through a batch API automatically via CI/CD to guarantee the batch discount on non-cached token volume.

---

## Open Questions (to refine later)

These are deliberately unresolved — the model above is generic until they're answered:

1. **Language/stack-specific token-per-LOC factor.** The flat `LOC × 12.5` density is a blended default; it should be tuned per primary language/stack (e.g. dense languages like JSON/config vs. terse ones like Python vs. verbose ones like Java/XML skew this materially). Codebase-*complexity* weighting (as opposed to per-language density) now has an optional, draft answer: `--indexer graphify` in [`prerun_estimate.py`](../scripts/prerun_estimate.py) reads an already-built graphify graph's edge-to-node ratio and applies a bounded multiplier to the agentic-traversal cost terms — see [LOCAL_PRESCAN_INDEXING.md](LOCAL_PRESCAN_INDEXING.md#alternate-indexers). Still flagged unverified/to-be-tuned, in particular the `BASELINE_RATIO` constant.
2. **Target integration surface — partially resolved.** Confirmed: Claude Security ships as *both* a hosted Enterprise product (no CLI/API access documented) and a Claude Code plugin (`/claude-security`, installed via `/plugin install claude-security@claude-plugins-official`) that runs inside a session and counts against the plan's usage limits rather than being billed separately. This repo's tooling targets the plugin path — see [CLAUDE_SECURITY_USAGE.md](CLAUDE_SECURITY_USAGE.md). Still open: whether a hard-cap gate should live in a Claude Code command/hook (blocking before `/claude-security` runs) versus a CI gate for a hypothetical future non-interactive invocation — no such CI/Actions surface is documented today.
3. **Preferred data format for the tool itself.** Whether the drop-in integration should be a Python class, an MCP server tool definition, or a Terraform module (for infra-as-code budget policy) is still open.
