"""Pre-run cost estimator for agentic security-scan workloads.

Estimates the dollar cost of a scan on the managed Claude Security product
(claude.ai/security, Enterprise-only), which runs exclusively on Claude
Mythos 5 and is "charged at direct token cost only" — no platform fee — per
Anthropic's published docs. That fixed model and direct billing are what
make a dollar pre-flight estimate meaningful here; the separate Claude
Security *plugin* for Claude Code has no fixed rate card of its own (it
runs on whichever model your account has access to) and isn't billed
separately at all — it draws from your Claude Code plan's usage limits,
the same pool /token-ops already tracks. See CLAUDE_SECURITY_USAGE.md.

Draft companion to SECURITY_SCAN_ESTIMATOR.md — see that doc for the
derivation of the formulas and the open questions pending refinement
(LOC-to-token density per language, output format).
"""


def estimate_claude_security_cost(
    loc: int,
    profile: str = "standard_taint_audit",
    model: str = "claude-mythos-5",
    is_batch: bool = False,
) -> dict:
    rates = {
        "claude-mythos-5": {
            "input": 10.0, "output": 50.0, "cache_read": 1.00, "cache_write": 20.0
        },
    }[model]

    profiles = {
        "pr_quick_scan": {"steps": 10, "ratio": 0.05, "tool_in": 8_000, "out": 1_200},
        "standard_taint_audit": {"steps": 150, "ratio": 0.20, "tool_in": 15_000, "out": 2_000},
        "deep_exploit_hunt": {"steps": 500, "ratio": 0.35, "tool_in": 25_000, "out": 4_000},
    }[profile]

    # 1. Base tokens calculation
    code_tokens = loc * 12.5
    overhead_tokens = code_tokens * 0.15
    write_tokens = code_tokens + overhead_tokens

    # 2. Dynamic execution token volumes
    steps = profiles["steps"]
    cache_read_tokens = write_tokens * profiles["ratio"] * steps
    dynamic_input_tokens = steps * profiles["tool_in"]
    output_tokens = steps * profiles["out"]

    # 3. Cost calculation (per million tokens)
    discount = 0.5 if is_batch else 1.0
    c_write = (write_tokens / 1_000_000) * rates["cache_write"]
    c_read = (cache_read_tokens / 1_000_000) * rates["cache_read"]
    c_input = (dynamic_input_tokens / 1_000_000) * rates["input"] * discount
    c_output = (output_tokens / 1_000_000) * rates["output"] * discount

    total_cost = c_write + c_read + c_input + c_output

    return {
        "estimated_total_usd": round(total_cost, 2),
        "breakdown": {
            "cache_write_cost": round(c_write, 2),
            "cache_read_cost": round(c_read, 2),
            "dynamic_input_cost": round(c_input, 2),
            "output_cost": round(c_output, 2),
        },
        "token_volumes": {
            "initial_cache_tokens": int(write_tokens),
            "total_cache_reads": int(cache_read_tokens),
            "total_uncached_input": int(dynamic_input_tokens),
            "total_output": int(output_tokens),
        },
    }
