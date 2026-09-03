"""Local, offline repo indexer for pre-run Claude Security cost estimation.

Counts lines of code per file/extension/directory without sending anything
over the network or to a model — stdlib only, same convention as the
Claude Security plugin itself. Output feeds prerun_estimate.py (or the
estimate_claude_security_cost function in estimate_claude_security_cost.py)
so a scan's rough token/dollar cost can be estimated, and its scope
narrowed, before invoking /claude-security. See ../LOCAL_PRESCAN_INDEXING.md.

Usage:
    python3 index_repo.py [--scope PATH] [--exclude GLOB ...] [--top N] [--out FILE]
"""

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# Extensions counted toward LOC — deliberately source-code-shaped. Anything
# else (images, binaries, lockfiles-by-extension, etc.) is tallied but
# excluded from the LOC total by default.
SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".kt", ".scala", ".rb", ".php",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".swift", ".m", ".mm",
    ".sh", ".bash", ".zsh", ".ps1",
    ".sql", ".graphql", ".proto",
    ".html", ".htm", ".css", ".scss", ".less", ".vue", ".svelte",
    ".yaml", ".yml", ".json", ".toml", ".xml",
    ".md", ".mdx", ".rst",
}

# Path fragments excluded even when git ls-files would otherwise include
# them (or when there's no .gitignore at all, e.g. a fresh checkout of
# vendored deps) — generated/vendored/build output isn't where
# vulnerabilities worth scanning tend to live, and inflates cost estimates.
DEFAULT_EXCLUDE_SUBSTRINGS = [
    "/node_modules/", "/vendor/", "/dist/", "/build/", "/.git/",
    "/venv/", "/.venv/", "/__pycache__/", "/.next/", "/.nuxt/",
    "/coverage/", "/.pytest_cache/", "/target/", "/.terraform/",
]

DEFAULT_EXCLUDE_BASENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Cargo.lock", "go.sum", "composer.lock", "Gemfile.lock",
}

DEFAULT_EXCLUDE_SUFFIXES = (".min.js", ".min.css", ".map", ".lock")


def _is_excluded(rel_path: str, extra_globs: list[str]) -> bool:
    posix = "/" + rel_path.replace(os.sep, "/")
    if any(frag in posix for frag in DEFAULT_EXCLUDE_SUBSTRINGS):
        return True
    base = os.path.basename(rel_path)
    if base in DEFAULT_EXCLUDE_BASENAMES:
        return True
    if base.endswith(DEFAULT_EXCLUDE_SUFFIXES):
        return True
    return any(fnmatch.fnmatch(posix, g) or fnmatch.fnmatch(base, g) for g in extra_globs)


def _git_tracked_files(root: Path) -> list[str] | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return [p for p in result.stdout.decode("utf-8", "ignore").split("\0") if p]


def _walk_files(root: Path) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "vendor", ".venv", "venv")]
        for name in filenames:
            out.append(str(Path(dirpath, name).relative_to(root)))
    return out


def count_lines(path: Path) -> int | None:
    try:
        with open(path, "r", encoding="utf-8", errors="strict") as f:
            return sum(1 for _ in f)
    except (UnicodeDecodeError, OSError):
        return None  # binary or unreadable — excluded from LOC


def index_repo(root: Path, scope: str | None, extra_excludes: list[str]) -> dict:
    base = (root / scope).resolve() if scope else root.resolve()
    tracked = _git_tracked_files(root)
    if tracked is not None:
        rel_files = [f for f in tracked if not scope or Path(f).is_relative_to(scope)]
    else:
        rel_files = [str(Path(scope, f)) if scope else f for f in _walk_files(base)]

    total_loc = 0
    file_count_considered = 0
    file_count_excluded = 0
    by_extension = defaultdict(lambda: {"files": 0, "loc": 0})
    by_top_dir = defaultdict(lambda: {"files": 0, "loc": 0})
    largest_files = []
    all_files = []

    for rel in rel_files:
        if _is_excluded(rel, extra_excludes):
            file_count_excluded += 1
            continue
        ext = Path(rel).suffix.lower()
        full = root / rel
        if ext not in SOURCE_EXTENSIONS or not full.is_file():
            file_count_excluded += 1
            continue
        loc = count_lines(full)
        if loc is None:
            file_count_excluded += 1
            continue

        file_count_considered += 1
        total_loc += loc
        by_extension[ext]["files"] += 1
        by_extension[ext]["loc"] += loc
        top_dir = rel.split("/", 1)[0] if "/" in rel else "."
        by_top_dir[top_dir]["files"] += 1
        by_top_dir[top_dir]["loc"] += loc
        largest_files.append((loc, rel))
        all_files.append(rel)

    largest_files.sort(reverse=True)
    return {
        "root": str(root.resolve()),
        "scope": scope or ".",
        "indexed_via": "git ls-files" if tracked is not None else "os.walk",
        "total_loc": total_loc,
        "files_counted": file_count_considered,
        "files_excluded": file_count_excluded,
        "by_extension": dict(sorted(by_extension.items(), key=lambda kv: -kv[1]["loc"])),
        "by_top_dir": dict(sorted(by_top_dir.items(), key=lambda kv: -kv[1]["loc"])),
        "largest_files": [{"loc": loc, "path": path} for loc, path in largest_files[:20]],
        "all_files": all_files,
        "source": "loc",
        "complexity": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repo root to index (default: cwd)")
    parser.add_argument("--scope", default=None, help="restrict indexing to this subdirectory")
    parser.add_argument("--exclude", action="append", default=[], help="extra glob to exclude (repeatable)")
    parser.add_argument("--top", type=int, default=20, help="how many largest files to report")
    parser.add_argument("--all-files", action="store_true", help="include the full indexed file list in the JSON")
    parser.add_argument("--out", default=None, help="write JSON here instead of stdout")
    args = parser.parse_args()

    result = index_repo(Path(args.root), args.scope, args.exclude)
    result["largest_files"] = result["largest_files"][: args.top]
    if not args.all_files:
        # Internal detail for token_sources.build_payload; omitted by default so
        # the CLI's JSON stays readable on large repos.
        result.pop("all_files", None)
    output = json.dumps(result, indent=2)

    if args.out:
        Path(args.out).write_text(output + "\n")
    else:
        print(output)


if __name__ == "__main__":
    sys.exit(main())
