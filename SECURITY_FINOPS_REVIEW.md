# Code review: security architecture & FinOps integrity

> **Status: review findings, not yet actioned.** Saved for later work, following the same convention as the (now-implemented) `PLAN_GRAPHIFY_INDEXER.md`. Delete or archive once the accepted items are addressed.
>
> **Reviewed:** commit `4aec70d` (post-graphify-indexer), all of `scripts/`, `schemas/`, `commands/`, `docs/`, `README.md`.
> **Date:** 2026-09-03
> **Lens:** AI-systems security architecture + FinOps. Every claim below was reproduced against the code — reproduction commands are in the appendix.

## Threat model, stated up front

Severity is meaningless without saying what this thing is. Today `token-finops` is a **local, offline, single-user advisory CLI**. It makes no network calls, runs no models, and writes nothing outside stdout. I verified that: `scripts/` imports stdlib only, and the sole subprocess call is `git ls-files` passed as an argument list (no `shell=True`, no injection surface). The "offline, no network, no model calls" guarantee the docs sell is **real and currently intact** — that's the most important security property in the repo and it should be treated as a regression-test-worthy invariant, not an implementation detail.

Under that model most conventional security findings here are genuinely Low. The severe findings are **FinOps model-integrity** ones, because the tool's entire product thesis is "puts a real number on token spend *before* you commit to it." A security review of a financial-estimation tool is mostly a review of whether the number can be trusted, and whether it can be *made* untrustworthy by someone else's input.

Two findings change severity sharply if the roadmap in `docs/LOCAL_PRESCAN_INDEXING.md` ("command-ifying this… a Phase 0 forecast step") is pursued, because that moves the tool from *advisory* to *gating*, and moves its inputs from *the user's own repo* to *whatever repo is being scanned*. Those are marked **↑ on promotion**.

---

## Part 1 — FinOps model integrity

### F1. The estimate is ~98% insensitive to the codebase it indexes, at the sizes it demos with — **High**

This is the headline finding. Of the four cost terms, only two (`cache_write`, `cache_read`) scale with LOC. The other two — `dynamic_input` (`steps × tool_input_per_step`) and `output` (`steps × output_per_step`) — are **pure functions of the profile constants and do not reference `loc` at all**.

Measured, `standard_taint_audit`:

| LOC | Total | LOC-driven $ | LOC-driven % |
|---|---|---|---|
| 0 | $37.50 | $0.00 | **0.0%** |
| 1,000 | $38.22 | $0.72 | **1.9%** |
| 10,000 | $44.69 | $7.19 | 16.1% |
| 100,000 | $109.38 | $71.87 | 65.7% |
| 500,000 | $396.88 | $359.37 | 90.5% |

An **empty repository is estimated at $37.50**. The README's own worked example (1,653 LOC → $38.69) is a number that is 98% profile-constant and 2% repository. The elaborate indexing apparatus — `index_repo.py`, the extension buckets, the largest-files report, and now the whole graphify complexity backend — is moving ~2% of the output at the scale the tool is demonstrated at.

That is not necessarily *wrong* (a scan's step count plausibly is the dominant cost driver), but it is **undisclosed**, and it inverts the tool's story. Users are told to index their repo to learn what a scan costs; the honest statement is "cost is dominated by scan depth, which you choose, and only weakly by codebase size, which you measure."

**Fix:** print the LOC-driven share alongside the total, e.g. `$38.69 (2% attributable to your 1,653 LOC; 98% is profile step-count)`. This is a one-line change to `prerun_estimate.py` and it converts a misleading number into an honest one. It also immediately tells a user that scoping down their repo will *not* save them money at small scale — which is currently the tool's implied advice and is wrong at that scale.

### F2. The "cache the whole codebase once" assumption is physically impossible above ~16k LOC — **High**

`write_tokens = loc × 12.5 × 1.15` is charged as a single cache write, i.e. the model assumes the entire codebase is loaded into one cached prompt prefix. Against real context limits:

| LOC | Implied single-prefix cache write |
|---|---|
| 16,000 | ~230,000 tokens |
| 100,000 | ~1,437,500 tokens |
| 500,000 | ~7,187,499 tokens |

Above roughly **16,000 LOC** this exceeds a 200k context window; the 500k-LOC guardrail the tool actually warns at is ~7.2M tokens, off by more than an order of magnitude from any available window. A real agentic scanner reads files selectively; it does not cache the repo.

The two findings compound badly and in opposite directions: **where the model is most sensitive to its input (large repos), its core assumption is most broken; where the assumption roughly holds (small repos), the input barely matters.** The model has a narrow validity band and it is not the band the tool advertises.

**Fix:** cap `write_tokens` at a documented per-model context ceiling and model the remainder as additional selective reads (i.e. more `dynamic_input`), or explicitly re-derive the large-repo branch. At minimum, document the ceiling and refuse to print a single-prefix cache-write figure above it. The existing 500k guardrail should be re-derived from the context window, not left at a round number.

### F3. One cache write is charged for a scan that will outlive the cache TTL — **Medium**

The rate card uses `cache_write_1h_per_m` (the 1-hour-TTL rate), but the model charges exactly one write regardless of profile. A 500-step `deep_exploit_hunt` will plausibly run past an hour, requiring the prefix to be re-written one or more times. Each re-write at 500k LOC is ~$143. The model has no re-write term, so it **systematically understates long scans** — the exact scans where the dollar figure matters most.

**Fix:** add an explicit `cache_rewrites` term (even a crude `ceil(estimated_wall_clock / ttl)`), or drop to the 5-minute cache rate and model re-writes per step-block. Either way, make the TTL assumption visible in the output.

### F4. `--batch` produces a number that this workload cannot realize — **Medium**

`--batch` applies a 50% discount to input and output. The Batch API is asynchronous with a long turnaround and no interactive tool-use loop. An agentic security scan is *definitionally* a sequential tool-use loop — it cannot run as a batch job. The flag therefore offers a one-keystroke path to a number that is half the true cost and unachievable in practice.

Separately, the discount is applied to `input`/`output` but **not** to `cache_read`/`cache_write`, with no stated rationale — worth confirming against the pricing docs either way.

**Fix:** remove `--batch` from this estimator, or gate it behind a clear "not applicable to interactive agentic scans — for modeling a hypothetical batch re-analysis only" warning printed with the result.

### F5. False precision on an admittedly unvalidated model — **Medium**

Output is rendered to the cent (`$229.78`) from step-count multipliers the docs openly call unverified defaults, plus a `BASELINE_RATIO` the last change flagged as draft. Four significant figures on a model with no empirical validation invites exactly the over-reliance the tool exists to prevent. The repo's honesty is in the *footnotes*; the *numbers* undercut it.

**Fix:** render a range, not a point (`~$180–$310`), or round to two significant figures. Carry the uncertainty in the primary artifact, not the caveat line.

### F6. The budget guardrail does not guard anything — **Medium** (**↑ High on promotion**)

`--budget-usd` prints ✅/❌ and then **exits 0 regardless**. Verified: all three profiles over budget still returns exit code 0. It cannot gate a hook, a CI job, or a pre-scan check — which is precisely the "Phase 0 forecast step" the docs propose. A budget control that cannot fail is a report, not a control.

**Fix:** exit non-zero when a selected profile breaches the budget (and add `--profile` so there is a *selected* profile to gate on). Keep the current report-only behavior available behind an explicit flag.

---

## Part 2 — Input integrity (the AI-specific attack surface)

### S1. `graph.json` is fully unvalidated and drives the dollar figure — **High** (**↑ Critical on promotion**)

`graphify_indexer.py` does `len(graph.get("nodes", []))` / `len(graph.get("edges", []))` with no type or schema validation. `len()` is happy to measure things that are not node lists. Demonstrated:

| `graph.json` contents | Resulting multiplier |
|---|---|
| `{"nodes":[],"edges":[]}` | **0.75×** (silent 25% discount) |
| `{"unexpected":true}` | **0.75×** (silent 25% discount) |
| `{"nodes":"abcdefghij","edges":"eeee…"}` (strings!) | **2.00×** (from string lengths) |

Two distinct defects:

1. **Type confusion.** A JSON file whose `nodes`/`edges` are strings, numbers-as-strings, or dicts yields a multiplier computed from `len()` of the wrong thing, with no error. The financial output is derived from `len()` of arbitrary JSON.
2. **Fail-open on a financial control.** A missing, empty, truncated, or wrong-shaped graph does not fail — it produces `ratio = 0.0` → the clamp floor → a **0.75× discount**. Corruption makes the scan look *cheaper*. The last change was careful to fail closed on a *missing file* (good, and the error message is genuinely well done) but fails open on a *malformed* one, which is the more likely real-world state.

**Fix:** validate before computing — assert `nodes` and `edges` are lists, require `node_count > 0`, and raise the same clean error used for the missing-file case otherwise. Never let the clamp floor be reachable via degenerate input; distinguish "genuinely sparse graph" (0.75× legitimately) from "I could not read this graph" (error). Also bound the read: `read_text()` + `json.loads()` on an unbounded file is a memory amplifier for a large graph.

### S2. An LLM-generated artifact is a trusted financial input — **Medium** (**↑ High on promotion**)

`graph.json` is produced by `/graphify`, whose extraction pass is LLM-driven and semantic. The estimator now treats that output as ground truth for a cost multiplier, with the validation gap above. Consequences worth stating plainly:

- **Non-determinism in a financial control.** Two graph builds of the same repo can yield different node/edge counts, hence different dollar figures, with nothing recording which graph produced a given estimate.
- **Indirect prompt injection reaches the cost model.** Content inside the repo being graphed influences the LLM's extraction. A repository containing text crafted to steer extraction (inflating or suppressing edges) can move the multiplier across its full 0.75×–2.0× range — a **2.7× swing** in the reported cost of scanning that repository. Today the repo you graph is your own, so this is theoretical. If this ever runs against third-party or dependency code, it is a live path from untrusted repo content to a budget decision.

**Fix:** record graph provenance in the output (graph file hash, mtime, node/edge counts) so an estimate is reproducible and auditable; warn when the graph is older than the working tree; and treat the multiplier as advisory — never let it be the sole basis of a gating decision (see F6).

### S3. The clamp is enforced in the wrong layer, and the cost function validates nothing — **Medium**

`estimate_claude_security_cost()` is documented as a **reference implementation** others are expected to import. Its only guard against absurd inputs lives in `graphify_indexer.py`, one layer up. Any other caller bypasses it entirely:

- `est(1000, complexity_multiplier=10_000)` → **$229,327.79**. No clamp, no error.
- `est(-1_000_000)` → **-$681.25**. Negative LOC yields negative dollars.
- `est(0)` → **$37.50** (see F1).

An invariant that protects a financial calculation belongs at the boundary of the function doing the calculation, not only in one of its callers.

**Fix:** validate in `estimate_claude_security_cost()` — reject `loc < 0`, reject non-finite or out-of-range `complexity_multiplier` (or clamp there and let the indexer stop clamping). Keep the indexer's clamp as defense in depth, not as the only defense.

---

## Part 3 — Conventional code security

### C1. `--scope` escapes the repo root on the non-git code path — **Low** (**↑ Medium on promotion**)

In a git repo, the `is_relative_to(scope)` filter neutralizes traversal (verified: `--scope ../../../../etc` → 0 files). But when `_git_tracked_files()` returns `None` — a non-git directory, or git unavailable — `base = (root / scope).resolve()` is walked directly with no containment check. Demonstrated:

```
$ python3 scripts/index_repo.py --root /tmp/nogit --scope ../../etc
root: /private/tmp/nogit   scope: ../../etc
files_counted: 2   total_loc: 807
leaked paths: ['../../etc/postfix/main.cf.proto', '../../etc/postfix/master.cf.proto']
```

It reports paths and line counts (not contents) of files outside the root. `pathlib` will also silently accept an *absolute* `--scope`, since `Path('/a') / '/etc'` is `/etc`. Low today because the operator supplies their own `--scope`; it matters the moment scope comes from a config file, a hook, or CI.

**Fix:** after resolving, assert `base.is_relative_to(root.resolve())` and reject otherwise. Two lines, closes both the traversal and absolute-path cases.

### C2. Unbounded / unfiltered file reads — **Low**

`count_lines()` reads any file passing `is_file()` with no size ceiling. `is_file()` correctly excludes FIFOs and device nodes (I checked — the `/dev/zero`-style hang is *not* reachable), but it **follows symlinks**, so a symlink in the repo to a large file elsewhere is read in full and its path reported. The cost is wall-clock, not memory (the count is a generator), so this is a nuisance, not a DoS.

**Fix:** skip files above a size ceiling (say 5 MB) and count them separately; optionally `os.path.realpath` and containment-check symlink targets.

### C3. `sys.path.insert(0, ...)` in two entry points — **Informational**

`prerun_estimate.py` and `graphify_indexer.py` both prepend their own directory to `sys.path`. For direct invocation this is redundant (Python already does it); when imported from elsewhere it silently gives `scripts/` precedence over stdlib for any colliding module name (`json.py`, `argparse.py`). No exploit path today — noting it because the docs invite importing these as a library.

**Fix:** prefer a relative import or a small package layout over `sys.path` mutation if this ever becomes an installable module.

---

## Part 4 — Governance & assurance

### G1. The documented config file is dead code — **Medium**

`schemas/claude_security_pre_run_estimator.json` holds the rate card and all three scan profiles. **Nothing reads it.** Verified: no reference to it anywhere in `scripts/` or `commands/`. Every value is independently hardcoded in `estimate_claude_security_cost.py`.

Meanwhile `README.md` states: *"The draft estimator's config is the rate card and scan-profile definitions in `schemas/claude_security_pre_run_estimator.json`."* That is **not true today** — editing that file changes nothing. A user tuning the rate card there would get silently stale numbers.

The two copies happen to agree right now (I diffed them: both `10.00 / 50.00 / 1.00 / 20.00 / 0.50`), so this is drift *risk*, not drift — but nothing prevents it, and the JSON carries the provenance (`rate_card_source`, retrieval date) that the code lacks.

**Fix:** load the schema at runtime and delete the hardcoded dict (single source of truth, and the provenance travels with the numbers). If loading is undesirable for the zero-dependency posture, add a test that fails when the two diverge — but do not leave the README claiming a config file that has no effect.

### G2. No tests, for a tool that emits financial figures — **Medium**

The README is explicit: "There's no build step or test suite," and verification is `ast.parse` — i.e. *does it parse*, not *is the arithmetic right*. During this session's own graphify work, the "byte-identical output" check had to be done by hand with `git stash`, and it was confounded by the source files' own LOC changing. That is a fragile way to protect a money calculation.

**Fix:** a single `tests/test_estimator.py` covering (a) golden values per profile at fixed LOC, (b) the rate card matching the schema (closes G1), (c) `complexity_multiplier=1.0` being exactly identity, (d) rejection of negative LOC / out-of-range multipliers, (e) the graphify malformed-input cases from S1. Roughly 60 lines of stdlib `unittest`, no new dependencies, preserving the zero-install posture.

### G3. Rate cards have provenance but no expiry — **Low**

The schema records `Retrieved 2026-09-02`, which is good practice and better than most. But nothing surfaces staleness: in six months the tool will still print confident dollar figures from a stale card, and the code path (which has no date at all) is the one actually doing the math.

**Fix:** carry the retrieval date into the runtime output and warn past a threshold — "rate card retrieved 2026-09-02 (247 days ago); re-verify against current pricing."

---

## What's already right

Worth recording, both to keep it and because a review that only lists defects misrepresents the codebase:

- **The offline guarantee is real.** Stdlib-only, no network imports, one `git ls-files` subprocess invoked as an argument list. The security property the product markets actually holds.
- **The refusal to auto-build a graph is exactly the right call**, for exactly the right reason (it would break the offline guarantee), and the missing-graph error message names the fix. That is well-designed fail-closed behavior — S1 is about extending it to malformed input, not about reversing it.
- **The multiplier is applied to the traversal terms only**, with the reasoning written into the code comment. That is a defensible modeling choice, documented where a maintainer will actually see it.
- **Exclusion lists are sensible** (vendored/generated/lockfile paths) and the rationale is stated.
- **The docs are unusually honest about what is unverified** — the problem identified in F5 is that the *numbers* don't inherit that honesty, not that the honesty is missing.

---

## Prioritized action list

| # | Finding | Severity | Effort | Order |
|---|---|---|---|---|
| S1 | Validate `graph.json`; fail closed on malformed, not open to 0.75× | High → Critical¹ | S | **1** |
| F1 | Disclose the LOC-driven share of the estimate | High | S | **2** |
| S3 | Validate inputs in the cost function itself | Medium | S | **3** |
| G1 | Load the schema, or test code-vs-schema; fix the README claim | Medium | S | **4** |
| F6 | Make `--budget-usd` exit non-zero on breach; add `--profile` | Medium → High¹ | S | **5** |
| G2 | Minimal `unittest` suite (locks 1–5 in place) | Medium | M | **6** |
| F2 | Cap cache-write at the context ceiling; re-derive the 500k guardrail | High | M | **7** |
| F5 | Render ranges instead of cents | Medium | S | 8 |
| F3 | Model cache re-writes across TTL | Medium | M | 9 |
| F4 | Remove or gate `--batch` | Medium | S | 10 |
| S2 | Record graph provenance/hash in output | Medium → High¹ | S | 11 |
| C1 | Containment-check `--scope` on the non-git path | Low → Medium¹ | S | 12 |
| C2 | Size ceiling on `count_lines()` | Low | S | 13 |
| G3 | Surface rate-card staleness at runtime | Low | S | 14 |
| C3 | Drop `sys.path` mutation if this becomes a package | Info | S | 15 |

¹ Escalates if the tool becomes a gating "Phase 0" hook/CI step, or is ever pointed at third-party code.

**Suggested first pass (items 1–6):** all small, all mutually reinforcing, and together they close every path where a wrong number can be produced *silently*. F2 is higher-severity but is a genuine modeling change deserving its own design pass, not a quick fix.

---

## Appendix — reproduction

```bash
# F1 — LOC sensitivity
python3 -c "import sys;sys.path.insert(0,'scripts')
from estimate_claude_security_cost import estimate_claude_security_cost as e
[print(l, e(l)['estimated_total_usd'], e(l)['breakdown']) for l in (0,1000,10000,100000,500000)]"

# S1 — malformed graph.json (run against a scratch repo with graphify-out/)
echo '{"nodes":[],"edges":[]}'                    > graphify-out/graph.json  # -> 0.75x
echo '{"unexpected":true}'                        > graphify-out/graph.json  # -> 0.75x
echo '{"nodes":"abcdefghij","edges":"eeee"}'      > graphify-out/graph.json  # -> len() of strings

# S3 — unvalidated cost-function inputs
python3 -c "import sys;sys.path.insert(0,'scripts')
from estimate_claude_security_cost import estimate_claude_security_cost as e
print(e(-1000000)['estimated_total_usd'], e(1000, complexity_multiplier=10000)['estimated_total_usd'])"

# F6 — budget breach still exits 0
python3 scripts/prerun_estimate.py --budget-usd 0.01 >/dev/null; echo $?

# C1 — scope escape on the non-git path
mkdir -p /tmp/nogit && echo 'x=1' > /tmp/nogit/a.py
python3 scripts/index_repo.py --root /tmp/nogit --scope ../../etc

# G1 — nothing reads the schema
grep -rn "claude_security_pre_run_estimator" scripts/ commands/ || echo "no readers"
```
