"""Pre-run forecast for a Claude Security scan: index the repo locally, then
estimate token/dollar cost across all scan profiles before invoking
/claude-security. See ../LOCAL_PRESCAN_INDEXING.md and
../SECURITY_SCAN_ESTIMATOR.md for the methodology and its open questions.

Usage:
    python3 prerun_estimate.py [--scope PATH] [--model claude-mythos-5.1] [--budget-usd N] [--batch]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from estimate_claude_security_cost import estimate_claude_security_cost  # noqa: E402
from index_repo import index_repo  # noqa: E402

PROFILE_ORDER = ["pr_quick_scan", "standard_taint_audit", "deep_exploit_hunt"]
PROFILE_STEPS = {"pr_quick_scan": 10, "standard_taint_audit": 150, "deep_exploit_hunt": 500}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repo root to index (default: cwd)")
    parser.add_argument("--scope", default=None, help="restrict indexing to this subdirectory")
    parser.add_argument("--exclude", action="append", default=[], help="extra glob to exclude (repeatable)")
    parser.add_argument("--model", default="claude-mythos-5.1", choices=["claude-mythos-5.1", "claude-opus-4.7"])
    parser.add_argument("--batch", action="store_true", help="apply the batch-API discount")
    parser.add_argument("--budget-usd", type=float, default=None, help="flag which profiles fit under this budget")
    args = parser.parse_args()

    idx = index_repo(Path(args.root), args.scope, args.exclude)
    loc = idx["total_loc"]

    print(f"Indexed {idx['files_counted']} files ({idx['files_excluded']} excluded) "
          f"via {idx['indexed_via']} under scope '{idx['scope']}': **{loc:,} LOC**\n")

    if loc > 500_000:
        biggest = next(iter(idx["by_top_dir"]), None)
        print(f"⚠️  {loc:,} LOC exceeds the 500k directory-scoping guardrail. "
              f"Consider --scope <subfolder> — largest top-level contributor: {biggest!r}.\n")

    print("| Profile | Steps | Est. total tokens | Est. cost (USD) | Fits budget? |")
    print("|---|---|---|---|---|")
    for profile in PROFILE_ORDER:
        result = estimate_claude_security_cost(loc, profile=profile, model=args.model, is_batch=args.batch)
        vols = result["token_volumes"]
        total_tokens = sum(vols.values())
        cost = result["estimated_total_usd"]
        fits = "—"
        if args.budget_usd is not None:
            fits = "✅" if cost <= args.budget_usd else "❌"
        print(f"| {profile} | {PROFILE_STEPS[profile]} | {total_tokens:,} | ${cost:,.2f} | {fits} |")

    print(f"\nModel: `{args.model}`{' (batch discount applied)' if args.batch else ''}. "
          f"Rate card and LOC-density factor are unverified defaults — see SECURITY_SCAN_ESTIMATOR.md.")


if __name__ == "__main__":
    sys.exit(main())
