"""Opt-in alternate indexer: reuses index_repo.py's LOC count but adds a
structural-complexity signal read from an already-built graphify graph
(graphify-out/graph.json). See ../docs/LOCAL_PRESCAN_INDEXING.md.

This indexer never builds or updates a graph itself — running /graphify can
cost real LLM tokens (semantic extraction) and sometimes a network call,
which would break this toolchain's offline/no-model-calls guarantee. If no
graph exists yet, index_repo() raises FileNotFoundError telling the user to
run /graphify first; there is no silent fallback to the plain LOC indexer.

Usage:
    python3 graphify_indexer.py [--scope PATH] [--exclude GLOB ...] [--top N] [--out FILE]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from index_repo import index_repo as _index_repo_loc  # noqa: E402

# Draft default, unverified — see docs/SECURITY_SCAN_ESTIMATOR.md open
# questions. Represents a "typical" edge-to-node ratio; repos above it get a
# multiplier > 1.0 (more interconnected, more agentic hops to trace),
# repos below it get < 1.0.
BASELINE_RATIO = 1.5

# Bounds the multiplier so a pathological graph (near-empty, or a hairball)
# can't produce an absurd cost swing.
MULTIPLIER_MIN = 0.75
MULTIPLIER_MAX = 2.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def index_repo(root: Path, scope: str | None, extra_excludes: list[str]) -> dict:
    graph_path = root.resolve() / "graphify-out" / "graph.json"
    if not graph_path.exists():
        raise FileNotFoundError(
            f"No graphify graph found at {graph_path}. "
            f"Run /graphify {root} first, then re-run this indexer."
        )

    result = _index_repo_loc(root, scope, extra_excludes)

    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    node_count = len(graph.get("nodes", []))
    edge_count = len(graph.get("edges", []))
    edge_to_node_ratio = (edge_count / node_count) if node_count else 0.0
    multiplier = _clamp(edge_to_node_ratio / BASELINE_RATIO, MULTIPLIER_MIN, MULTIPLIER_MAX)

    result["source"] = "graphify"
    result["complexity"] = {
        "node_count": node_count,
        "edge_count": edge_count,
        "edge_to_node_ratio": edge_to_node_ratio,
        "multiplier": multiplier,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repo root to index (default: cwd)")
    parser.add_argument("--scope", default=None, help="restrict indexing to this subdirectory")
    parser.add_argument("--exclude", action="append", default=[], help="extra glob to exclude (repeatable)")
    parser.add_argument("--top", type=int, default=20, help="how many largest files to report")
    parser.add_argument("--out", default=None, help="write JSON here instead of stdout")
    args = parser.parse_args()

    result = index_repo(Path(args.root), args.scope, args.exclude)
    result["largest_files"] = result["largest_files"][: args.top]
    output = json.dumps(result, indent=2)

    if args.out:
        Path(args.out).write_text(output + "\n")
    else:
        print(output)


if __name__ == "__main__":
    sys.exit(main())
