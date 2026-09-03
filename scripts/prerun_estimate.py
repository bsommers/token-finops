"""Pre-run forecast for a Claude Security scan: measure the repo locally, then
estimate token/dollar cost across all scan profiles before running a scan on
the managed Claude Security product — the surface where a dollar figure is
directly invoice-comparable, since it's billed at direct token cost on a fixed
model. See ../docs/CLAUDE_SECURITY_USAGE.md for why the Claude Code plugin path
isn't estimated the same way, and ../docs/LOCAL_PRESCAN_INDEXING.md and
../docs/SECURITY_SCAN_ESTIMATOR.md for the methodology and its open questions.

Usage:
    python3 prerun_estimate.py [--scope PATH] [--model MODEL]
                               [--token-source {loc,repomix,gitingest,count-tokens}]
                               [--indexer {loc,graphify}] [--budget-usd N] [--profile P]

Exit codes: 0 = fine, 1 = error, 2 = budget breached (so this can gate CI).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import token_sources  # noqa: E402
from estimate_claude_security_cost import estimate_claude_security_cost  # noqa: E402
from graphify_indexer import index_repo as index_repo_graphify  # noqa: E402
from index_repo import index_repo as index_repo_loc  # noqa: E402
from rate_cards import known_models, load_schema, staleness  # noqa: E402

PROFILE_ORDER = ["pr_quick_scan", "standard_taint_audit", "deep_exploit_hunt"]


def main() -> None:
    schema = load_schema()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repo root to index (default: cwd)")
    parser.add_argument("--scope", default=None, help="restrict indexing to this subdirectory")
    parser.add_argument("--exclude", action="append", default=[], help="extra glob to exclude (repeatable)")
    parser.add_argument("--model", default="claude-mythos-5", choices=known_models(schema))
    parser.add_argument("--indexer", default="loc", choices=["loc", "graphify"],
                        help="complexity backend: 'loc' (default) or 'graphify' (needs a built graph)")
    parser.add_argument("--token-source", default="loc",
                        choices=["loc", "repomix", "gitingest", "count-tokens"],
                        help="how to count tokens. 'loc' (default) is an offline heuristic; "
                             "repomix/gitingest pack and measure offline; count-tokens is exact "
                             "but SENDS YOUR SOURCE to Anthropic's API")
    parser.add_argument("--count-tokens-model", default=None,
                        help="model to count with (default: --model). Every model in the rate "
                             "card shares the current tokenizer, so use one you can access.")
    parser.add_argument("--batch", action="store_true",
                        help="apply Batch API rates. NOT applicable to interactive agentic scans "
                             "— Anthropic's docs state the batch discount does not apply to "
                             "stateful sessions. For hypothetical modeling only.")
    parser.add_argument("--budget-usd", type=float, default=None, help="flag which profiles fit under this budget")
    parser.add_argument("--profile", default=None, choices=PROFILE_ORDER,
                        help="gate on this profile: exit 2 if it breaches --budget-usd")
    args = parser.parse_args()

    # --- measure the repo -------------------------------------------------
    index_repo = index_repo_graphify if args.indexer == "graphify" else index_repo_loc
    try:
        idx = index_repo(Path(args.root), args.scope, args.exclude)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    loc = idx["total_loc"]
    multiplier = idx["complexity"]["multiplier"] if idx["complexity"] else 1.0

    root = Path(args.root)
    density = schema["token_density"]
    try:
        if args.token_source == "loc":
            tok = token_sources.from_loc(loc, density["loc_heuristic_tokens_per_loc"])
        elif args.token_source == "repomix":
            tok = token_sources.from_repomix(root, root)
        elif args.token_source == "gitingest":
            tok = token_sources.from_gitingest(root, root)
        else:
            tok = token_sources.from_count_tokens(
                root, args.scope, args.exclude,
                args.count_tokens_model or args.model,
            )
    except token_sources.TokenSourceError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Indexed {idx['files_counted']} files ({idx['files_excluded']} excluded) "
          f"via {idx['indexed_via']} under scope '{idx['scope']}': **{loc:,} LOC**")
    marker = "exact" if tok["exact"] else "estimated"
    print(f"Token payload ({marker}, source `{tok['token_source']}`): "
          f"**{tok['code_tokens']:,} tokens** — {tok['detail']}")
    if tok["network_used"]:
        print("⚠️  This run made a network call and sent your source code to Anthropic's API.")
    print()

    # --- estimate ---------------------------------------------------------
    print("| Profile | Steps | Est. total tokens | Est. cost (USD) | Fits budget? |")
    print("|---|---|---|---|---|")
    breached = False
    for profile in PROFILE_ORDER:
        result = estimate_claude_security_cost(
            code_tokens=tok["code_tokens"], profile=profile, model=args.model,
            is_batch=args.batch, complexity_multiplier=multiplier, schema=schema,
        )
        vols = result["token_volumes"]
        total_tokens = sum(vols.values())
        cost = result["estimated_total_usd"]
        fits = "—"
        if args.budget_usd is not None:
            over = cost > args.budget_usd
            fits = "❌" if over else "✅"
            if over and profile == (args.profile or profile) and args.profile:
                breached = True
        steps = schema["scan_profiles"][profile]["avg_steps"]
        print(f"| {profile} | {steps} | {total_tokens:,} | ${cost:,.2f} | {fits} |")
        if result["context_overflow_tokens"]:
            print(f"|   ↳ note | | {result['context_overflow_tokens']:,} tokens exceed the "
                  f"{schema['rate_cards'][args.model]['context_window']:,}-token context window "
                  f"and are billed as selective reads, not cache | | |")

    if idx["complexity"]:
        c = idx["complexity"]
        print(f"\nComplexity: edge/node ratio {c['edge_to_node_ratio']:.2f} "
              f"(from graphify-out/graph.json, {c['node_count']:,} nodes / {c['edge_count']:,} edges) "
              f"→ {c['multiplier']:.2f}x cost multiplier applied.")

    # --- provenance -------------------------------------------------------
    days, stale = staleness(schema)
    card = schema["rate_cards"][args.model]
    print(f"\nModel: `{args.model}` ({card['display_name']}, {card['access']})"
          f"{' — BATCH RATES APPLIED (not valid for interactive scans)' if args.batch else ''}")
    print(f"Rate card retrieved {schema['rate_card_retrieved']} ({days} days ago)"
          f"{' — ⚠️  STALE, re-verify against current pricing' if stale else ''}.")
    if not tok["exact"]:
        print("Token count is an estimate, not a measurement — for an exact figure use "
              "`--token-source count-tokens` (network).")

    if args.profile and args.budget_usd is not None and breached:
        print(f"\n❌ Budget gate: `{args.profile}` exceeds ${args.budget_usd:,.2f}.", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    sys.exit(main())
