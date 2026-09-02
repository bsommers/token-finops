# Claude Security Pre-Run Cost Estimator (Draft)

> **Status: draft, pending refinement.** This is a *pre-execution* cost estimator for agentic security-scan workloads (e.g. Claude Security-style multi-stage scans: indexing → call-graph traversal → dynamic tool calls → patch generation) — not the same thing as `/token-ops`. `/token-ops` forecasts and monitors a **live coding session's** token budget turn by turn; this estimator predicts the **dollar cost of a scan job before it runs**, from static inputs (lines of code, scan depth) alone, so it can gate whether the job runs at all. See [FORECASTING.md](FORECASTING.md) for the session-monitoring methodology this complements.

Open items below are intentionally left as TODOs — this doc captures the model as received, to be tuned once those are resolved.

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

Machine-readable schema: [`schemas/claude_security_pre_run_estimator.json`](schemas/claude_security_pre_run_estimator.json).

> ⚠️ **Rate card and model IDs are unverified.** `claude-mythos-5.1` and `claude-opus-4.7` don't match this repo's known current model IDs (`claude-fable-5`, `claude-opus-5`, `claude-sonnet-5`, `claude-haiku-4-5-20251001`). Confirm both the model identifiers and the per-token rates against the live pricing page before wiring this into any real budget gate — see [claude-api skill](https://claude.com) or the current Anthropic pricing docs as the source of truth, not this file.

## Executable Estimator

Reference implementation: [`scripts/estimate_claude_security_cost.py`](scripts/estimate_claude_security_cost.py) — `estimate_claude_security_cost(loc, profile, model, is_batch)`, returns estimated total USD plus a cost and token-volume breakdown.

## Guardrails to Implement Before a Scan Runs

- **Hard-cap budget gating**: intercept jobs where `estimated_total_usd > budget_threshold` before triggering the scan.
- **Directory scoping**: if `loc > 500,000`, prompt for scoping to a sub-folder (e.g. `/services/auth/`) rather than scanning the whole repo root.
- **Batch routing**: route full-repository scheduled/scanning audits through a batch API automatically via CI/CD to guarantee the batch discount on non-cached token volume.

---

## Open Questions (to refine later)

These are deliberately unresolved — the model above is generic until they're answered:

1. **Language/stack-specific token-per-LOC factor.** The flat `LOC × 12.5` density is a blended default; it should be tuned per primary language/stack (e.g. dense languages like JSON/config vs. terse ones like Python vs. verbose ones like Java/XML skew this materially).
2. **Target integration surface.** Whether this estimator is meant to run as a CLI pre-commit hook, a GitHub Actions gate, or a direct Claude Platform API pre-flight check changes both the interface shape and where the hard-cap guardrail actually gets enforced.
3. **Preferred data format for the tool itself.** Whether the drop-in integration should be a Python class, an MCP server tool definition, or a Terraform module (for infra-as-code budget policy) is still open.
