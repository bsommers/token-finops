"""Single source of truth for rate cards, scan profiles, and token density.

Loads schemas/claude_security_pre_run_estimator.json at runtime so the numbers
the CLI prints are the numbers in the config file — previously the rate card
was hardcoded in estimate_claude_security_cost.py while the schema sat unread,
which meant editing the documented config changed nothing.

Stdlib only; reads one local JSON file and makes no network calls.
"""

import json
from datetime import date, datetime
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "claude_security_pre_run_estimator.json"


def load_schema(path: Path | None = None) -> dict:
    p = path or SCHEMA_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"Rate-card schema not found at {p}. The estimator has no hardcoded "
            f"fallback rate card — restore the file or pass an explicit path."
        )
    return json.loads(p.read_text(encoding="utf-8"))


def rate_card(model: str, schema: dict | None = None) -> dict:
    s = schema or load_schema()
    cards = s["rate_cards"]
    if model not in cards:
        raise KeyError(f"Unknown model {model!r}. Known: {', '.join(sorted(cards))}")
    return cards[model]


def scan_profile(profile: str, schema: dict | None = None) -> dict:
    s = schema or load_schema()
    profiles = s["scan_profiles"]
    if profile not in profiles:
        raise KeyError(f"Unknown profile {profile!r}. Known: {', '.join(profiles)}")
    return profiles[profile]


def known_models(schema: dict | None = None) -> list[str]:
    return sorted((schema or load_schema())["rate_cards"])


def staleness(schema: dict | None = None) -> tuple[int, bool]:
    """Return (days_since_retrieval, is_stale) for the rate card.

    A confident dollar figure printed from a rate card nobody has re-checked in
    months is exactly the failure this repo exists to prevent, so the age is
    surfaced at runtime rather than left in a JSON field nobody reads.
    """
    s = schema or load_schema()
    retrieved = datetime.strptime(s["rate_card_retrieved"], "%Y-%m-%d").date()
    days = (date.today() - retrieved).days
    return days, days > s.get("rate_card_stale_after_days", 90)
