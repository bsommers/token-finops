"""Pluggable ways to turn a repository into the token count the estimator bills.

The default (`loc`) keeps the repo's offline, zero-setup guarantee: a LOC count
multiplied by a heuristic tokens-per-LOC factor. The alternates trade some of
that for accuracy:

    loc           offline, zero setup, heuristic       (default)
    repomix       offline, needs npx/repomix           packs the repo, measures the payload
    gitingest     offline, needs gitingest             packs the repo, measures the payload
    count-tokens  NETWORK + API KEY, exact             Anthropic's own tokenizer

Two things worth knowing before trusting a number from here:

1. **Repomix and Gitingest report their own token counts using OpenAI's
   tokenizer (tiktoken).** Those numbers are wrong for Claude — tiktoken
   undercounts Claude tokens by roughly 15-20% on prose and by more on code.
   This module therefore uses those tools only as *packers* and derives the
   token count itself from the packed payload; it never reads back their
   reported token estimate.

2. **Only `count-tokens` is exact**, and it is the one source that breaks the
   repo's offline guarantee — it sends your packed source code to Anthropic's
   API. It is strictly opt-in and never runs unless explicitly selected.

See ../docs/LOCAL_PRESCAN_INDEXING.md.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from index_repo import index_repo as _index_repo_loc  # noqa: E402

# Anthropic's published figure for the current tokenizer (Claude 4.7 and later,
# which includes every model in the rate card): 1M tokens is roughly 2.5M
# Unicode characters. Used to convert a packed payload's size into tokens
# without a network call.
# Source: platform.claude.com/docs/en/about-claude/models/overview (context-window note).
CHARS_PER_TOKEN = 2.5

# count_tokens payload chunk size, in characters. Very large single requests are
# rejected; counts are summed across chunks, which is approximate only at the
# chunk boundaries (a handful of tokens across the whole repo).
COUNT_TOKENS_CHUNK_CHARS = 2_000_000


class TokenSourceError(RuntimeError):
    """Raised with a user-facing message when a token source cannot run."""


def _result(source: str, code_tokens: int, exact: bool, detail: str, network: bool) -> dict:
    return {
        "token_source": source,
        "code_tokens": int(code_tokens),
        "exact": exact,
        "detail": detail,
        "network_used": network,
    }


def from_loc(total_loc: int, tokens_per_loc: float) -> dict:
    """Default: the LOC heuristic. Offline, zero setup, unverified factor."""
    return _result(
        "loc",
        total_loc * tokens_per_loc,
        exact=False,
        detail=f"{total_loc:,} LOC x {tokens_per_loc} tokens/LOC (unverified heuristic)",
        network=False,
    )


def _run_packer(cmd: list[str], root: Path, out: Path, tool: str) -> str:
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, timeout=600)
    except FileNotFoundError:
        raise TokenSourceError(
            f"{tool} not found. Install it, or use --token-source loc (the offline default)."
        )
    except subprocess.TimeoutExpired:
        raise TokenSourceError(f"{tool} timed out after 600s packing {root}.")
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "ignore").strip().splitlines()
        tail = err[-1] if err else f"exit {proc.returncode}"
        raise TokenSourceError(f"{tool} failed: {tail}")
    if not out.exists():
        raise TokenSourceError(f"{tool} reported success but wrote no output at {out}.")
    return out.read_text(encoding="utf-8", errors="ignore")


def from_repomix(root: Path, out_dir: Path) -> dict:
    """Pack with repomix, then measure the payload ourselves.

    Deliberately ignores repomix's own token count — that figure comes from
    tiktoken and is not valid for Claude billing.
    """
    out = out_dir / "repomix-output.xml"
    packed = _run_packer(
        ["npx", "-y", "repomix", "--style", "xml", "--output", str(out)],
        root, out, "repomix",
    )
    chars = len(packed)
    return _result(
        "repomix",
        chars / CHARS_PER_TOKEN,
        exact=False,
        detail=(f"{chars:,} packed chars / {CHARS_PER_TOKEN} chars-per-token "
                f"(repomix payload; its own tiktoken count ignored — not valid for Claude)"),
        network=False,
    )


def from_gitingest(root: Path, out_dir: Path) -> dict:
    """Pack with gitingest, then measure the payload ourselves."""
    out = out_dir / "gitingest-output.txt"
    packed = _run_packer(
        ["gitingest", str(root), "--output", str(out)],
        root, out, "gitingest",
    )
    chars = len(packed)
    return _result(
        "gitingest",
        chars / CHARS_PER_TOKEN,
        exact=False,
        detail=(f"{chars:,} packed chars / {CHARS_PER_TOKEN} chars-per-token "
                f"(gitingest payload; its own token count ignored — not valid for Claude)"),
        network=False,
    )


def build_payload(root: Path, scope: str | None, extra_excludes: list[str]) -> tuple[str, int]:
    """Concatenate the files index_repo already selected, as count_tokens input.

    This is the same file set the LOC path measures, so the exact count that
    comes back describes the payload the estimate is actually about.
    """
    idx = _index_repo_loc(root, scope, extra_excludes)
    parts = []
    for entry in idx.get("all_files", []):
        full = root / entry
        try:
            parts.append(f"--- {entry} ---\n" + full.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return "\n\n".join(parts), idx["files_counted"]


def from_count_tokens(root: Path, scope: str | None, extra_excludes: list[str], model: str) -> dict:
    """Exact count via Anthropic's count_tokens endpoint.

    NETWORK CALL. Sends the packed source to Anthropic. Opt-in only.
    """
    try:
        from anthropic import Anthropic
    except ImportError:
        raise TokenSourceError(
            "The `anthropic` package is required for --token-source count-tokens. "
            "Install it (`pip install anthropic`), or use an offline source "
            "(loc, repomix, gitingest)."
        )

    payload, file_count = build_payload(root, scope, extra_excludes)
    if not payload.strip():
        raise TokenSourceError(f"No indexable source files found under {root} — nothing to count.")

    try:
        client = Anthropic()
    except Exception as e:  # noqa: BLE001 - surfaced verbatim to the user
        raise TokenSourceError(f"Could not construct the Anthropic client: {e}")

    chunks = [payload[i:i + COUNT_TOKENS_CHUNK_CHARS]
              for i in range(0, len(payload), COUNT_TOKENS_CHUNK_CHARS)]
    total = 0
    try:
        for chunk in chunks:
            resp = client.messages.count_tokens(
                model=model,
                messages=[{"role": "user", "content": chunk}],
            )
            total += resp.input_tokens
    except Exception as e:  # noqa: BLE001 - network/auth/access errors are user-facing
        raise TokenSourceError(
            f"count_tokens failed against model {model!r}: {e}\n"
            f"  If this is an access error, count with a model you can reach via "
            f"--count-tokens-model (every model in the rate card shares the current "
            f"tokenizer, so the count is the same)."
        )

    approx = " (summed across %d chunks)" % len(chunks) if len(chunks) > 1 else ""
    return _result(
        "count-tokens",
        total,
        exact=True,
        detail=(f"exact count from Anthropic count_tokens for {model} over "
                f"{file_count:,} files, {len(payload):,} chars{approx}"),
        network=True,
    )
