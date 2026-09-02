"""Pre-run cost estimator for agentic security-scan workloads.

Draft companion to SECURITY_SCAN_ESTIMATOR.md — see that doc for the
derivation of the formulas and the open questions pending refinement
(rate card / model IDs, LOC-to-token density per language, output format).
"""


def estimate_claude_security_cost(
    loc: int,
    profile: str = "standard_taint_audit",
    model: str = "claude-mythos-5.1",
    is_batch: bool = False,
) -> dict:
    rates = {
        "claude-mythos-5.1": {
            "input": 10.0, "output": 50.0, "cache_read": 0.25, "cache_write": 20.0
        },
        "claude-opus-4.7": {
            "input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_write": 6.25
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
