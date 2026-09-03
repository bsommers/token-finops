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

> ✅ **Rate card verified 2026-09-03** against [Anthropic's pricing page](https://platform.claude.com/docs/en/about-claude/pricing) (model-pricing, prompt-caching, and batch tables). The schema is now **loaded at runtime** — editing it changes what the CLI prints; there is no hardcoded rate card in the code.
>
> The estimator targets the **managed** Claude Security product, which runs on a Project Glasswing Mythos model and is charged at direct token cost. Five models are carried, because the choice materially changes the bill:
>
> | Model | Input | Output | Cache read | 1h cache write |
> |---|---|---|---|---|
> | `claude-mythos-5` | $10 | $50 | **$1.00** | $20 |
> | `claude-mythos-5-1` | $10 | $50 | **$0.25** | $20 |
> | `claude-fable-5` | $10 | $50 | $1.00 | $20 |
> | `claude-fable-5-1` | $10 | $50 | $0.25 | $20 |
> | `claude-opus-5` | $5 | $25 | $0.50 | $10 |
>
> ⚠️ **Cache reads are `0.1x` base input on every model except Claude Fable 5.1 and Claude Mythos 5.1, which are `0.025x`** — $0.25/MTok rather than $1.00/MTok. On a cache-read-heavy scan that 4x difference is the single largest lever in the whole model: a `deep_exploit_hunt` on a 500k-LOC repo costs **$481.88 on `claude-mythos-5` vs $350.62 on `claude-mythos-5-1` (−27%)**, from the model choice alone.
>
> The Mythos models are Project Glasswing limited-availability; `claude-fable-5-1` is the generally-available equivalent at identical pricing. The separate **Claude Security plugin for Claude Code** isn't billed against any of these — it draws from your Claude Code plan's usage limits. See [CLAUDE_SECURITY_USAGE.md](CLAUDE_SECURITY_USAGE.md).

## Executable Estimator

Reference implementation: [`scripts/estimate_claude_security_cost.py`](../scripts/estimate_claude_security_cost.py) — `estimate_claude_security_cost(loc=..., code_tokens=..., profile, model, is_batch, complexity_multiplier)` — pass `code_tokens` from a measured/exact source in preference to `loc`, returns estimated total USD plus a cost and token-volume breakdown. Rather than guessing `loc`, feed it a real count from [`scripts/index_repo.py`](../scripts/index_repo.py), or run the two chained via [`scripts/prerun_estimate.py`](../scripts/prerun_estimate.py) for a one-shot table across all three profiles — see [LOCAL_PRESCAN_INDEXING.md](LOCAL_PRESCAN_INDEXING.md).

## Guardrails to Implement Before a Scan Runs

- **Hard-cap budget gating**: intercept jobs where `estimated_total_usd > budget_threshold` before triggering the scan — `prerun_estimate.py --budget-usd N` implements this as a ✅/❌ flag per profile.
- **Directory scoping**: if `loc > 500,000`, prompt for scoping to a sub-folder (e.g. `/services/auth/`) rather than scanning the whole repo root — `prerun_estimate.py` warns and names the largest top-level directory once this threshold is crossed.
- ~~**Batch routing**~~ — **retracted.** This guardrail was wrong. Anthropic's pricing docs state the Batch API discount does **not** apply to stateful, interactive agent sessions: *"Sessions are stateful and interactive. There is no batch mode."* An agentic security scan is a sequential tool-use loop and cannot be batched. `--batch` is retained for hypothetical modeling only and prints a warning when used; do not budget against its output.

---

## Open Questions (to refine later)

These are deliberately unresolved — the model above is generic until they're answered:

1. **Language/stack-specific token-per-LOC factor — now avoidable.** The flat `LOC × 12.5` density is a blended default. Two developments since it was written:
   - **It can be sidestepped entirely.** `--token-source count-tokens` measures the real payload with Anthropic's own tokenizer (free endpoint), and `--token-source repomix|gitingest` measures the packed payload offline. The heuristic is now the *default*, not the only option — see [LOCAL_PRESCAN_INDEXING.md](LOCAL_PRESCAN_INDEXING.md#token-sources-how-the-payload-gets-counted).
   - **It is probably ~30% low.** Anthropic's docs state that Claude 4.7-and-later models — every model in this rate card — use a tokenizer producing roughly **30% more tokens for the same text** than the Sonnet 4.6-era tokenizer. A factor carried over from an older model understates by about that much.
   Codebase-*complexity* weighting (as opposed to per-language density) has a separate optional answer via `--indexer graphify`, still flagged unverified — in particular the `BASELINE_RATIO` constant.
2. **Target integration surface — partially resolved.** Confirmed: Claude Security ships as *both* a hosted Enterprise product (no CLI/API access documented) and a Claude Code plugin (`/claude-security`, installed via `/plugin install claude-security@claude-plugins-official`) that runs inside a session and counts against the plan's usage limits rather than being billed separately. This repo's tooling targets the plugin path — see [CLAUDE_SECURITY_USAGE.md](CLAUDE_SECURITY_USAGE.md). Still open: whether a hard-cap gate should live in a Claude Code command/hook (blocking before `/claude-security` runs) versus a CI gate for a hypothetical future non-interactive invocation — no such CI/Actions surface is documented today.
3. **Preferred data format for the tool itself.** Whether the drop-in integration should be a Python class, an MCP server tool definition, or a Terraform module (for infra-as-code budget policy) is still open.
