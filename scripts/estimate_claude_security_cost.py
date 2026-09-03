"""Pre-run cost estimator for agentic security-scan workloads.

Estimates the dollar cost of a scan on the managed Claude Security product
(claude.ai/security), which runs on a Project Glasswing Mythos model and is
charged at direct token cost. That fixed model and direct billing are what
make a dollar pre-flight estimate meaningful here; the separate Claude
Security *plugin* for Claude Code has no fixed rate card of its own (it runs
on whichever model your account has access to) and isn't billed separately at
all — it draws from your Claude Code plan's usage limits, the same pool
/token-ops already tracks. See CLAUDE_SECURITY_USAGE.md.

Rate cards and scan profiles are loaded from
schemas/claude_security_pre_run_estimator.json — this module has no hardcoded
pricing. See SECURITY_SCAN_ESTIMATOR.md for the derivation of the formulas and
the open questions pending refinement.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rate_cards import load_schema, rate_card, scan_profile  # noqa: E402

# Bounds on the structural-complexity multiplier. Enforced here, at the
# boundary of the function that does the arithmetic, rather than only in the
# indexer that happens to supply it — any other caller of this reference
# implementation gets the same guarantee.
MULTIPLIER_MIN = 0.75
MULTIPLIER_MAX = 2.0


def estimate_claude_security_cost(
    loc: int | None = None,
    profile: str = "standard_taint_audit",
    model: str = "claude-mythos-5",
    is_batch: bool = False,
    complexity_multiplier: float = 1.0,
    code_tokens: int | None = None,
    schema: dict | None = None,
) -> dict:
    """Estimate the cost of one scan.

    Supply either `loc` (converted with the unverified tokens-per-LOC
    heuristic) or `code_tokens` (a measured or exact count from
    token_sources.py). `code_tokens` wins when both are given.
    """
    s = schema or load_schema()
    rates = rate_card(model, s)
    profiles = scan_profile(profile, s)
    density = s["token_density"]

    if code_tokens is None and loc is None:
        raise ValueError("Supply either loc= or code_tokens=.")
    if code_tokens is not None and code_tokens < 0:
        raise ValueError(f"code_tokens must be >= 0, got {code_tokens}")
    if loc is not None and loc < 0:
        raise ValueError(f"loc must be >= 0, got {loc}")
    if not math.isfinite(complexity_multiplier):
        raise ValueError(f"complexity_multiplier must be finite, got {complexity_multiplier}")
    if not (MULTIPLIER_MIN <= complexity_multiplier <= MULTIPLIER_MAX):
        raise ValueError(
            f"complexity_multiplier must be in [{MULTIPLIER_MIN}, {MULTIPLIER_MAX}], "
            f"got {complexity_multiplier}"
        )

    # 1. Base tokens. Either measured directly, or derived from LOC.
    if code_tokens is not None:
        base_code_tokens = float(code_tokens)
    else:
        base_code_tokens = loc * density["loc_heuristic_tokens_per_loc"]
    overhead_tokens = base_code_tokens * density["overhead_factor"]
    write_tokens = base_code_tokens + overhead_tokens

    # The whole-codebase cache write assumes the payload fits one cached prompt
    # prefix. Above the context window that is physically impossible, so the
    # cached portion is capped and the remainder is treated as selective reads.
    context_window = rates["context_window"]
    cached_tokens = min(write_tokens, context_window)
    uncached_spill = max(0.0, write_tokens - context_window)

    # 2. Dynamic execution token volumes. The complexity multiplier scales only
    # the terms representing agentic traversal work — more interconnected code
    # means more cross-file hops. It does not touch the one-time cache write or
    # the flat per-step output term.
    steps = profiles["avg_steps"]
    cache_read_tokens = cached_tokens * profiles["cache_subgraph_ratio"] * steps * complexity_multiplier
    dynamic_input_tokens = (steps * profiles["tool_input_per_step"] + uncached_spill) * complexity_multiplier
    output_tokens = steps * profiles["output_per_step"]

    # 3. Cost. Batch rates come from the rate card rather than a blanket 0.5
    # factor, and deliberately do not discount cache operations.
    if is_batch:
        input_rate = rates["batch_input_per_m"]
        output_rate = rates["batch_output_per_m"]
    else:
        input_rate = rates["base_input_per_m"]
        output_rate = rates["output_per_m"]

    c_write = (cached_tokens / 1_000_000) * rates["cache_write_1h_per_m"]
    c_read = (cache_read_tokens / 1_000_000) * rates["cache_read_per_m"]
    c_input = (dynamic_input_tokens / 1_000_000) * input_rate
    c_output = (output_tokens / 1_000_000) * output_rate

    total_cost = c_write + c_read + c_input + c_output

    return {
        "estimated_total_usd": round(total_cost, 2),
        "model": model,
        "profile": profile,
        "breakdown": {
            "cache_write_cost": round(c_write, 2),
            "cache_read_cost": round(c_read, 2),
            "dynamic_input_cost": round(c_input, 2),
            "output_cost": round(c_output, 2),
        },
        "token_volumes": {
            "initial_cache_tokens": int(cached_tokens),
            "total_cache_reads": int(cache_read_tokens),
            "total_uncached_input": int(dynamic_input_tokens),
            "total_output": int(output_tokens),
        },
        "context_overflow_tokens": int(uncached_spill),
    }
