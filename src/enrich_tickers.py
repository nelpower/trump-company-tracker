"""Fill in ``ticker_if_public`` / ``exchange_if_public`` when missing.

Order of preference:
1. The alias table already filled it in during extraction (the common case).
2. The local SEC ``company_tickers.json`` (offline; optional file).
3. yfinance lookup (optional, network, off by default).

Hard rule: if nothing authoritative is found we leave the ticker BLANK and set
``company_status = unknown``. We never guess a ticker.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from src.config import SEC_TICKERS_PATH
from src.models import Mention


def _simplify(name: str) -> str:
    """Strip corporate suffixes / punctuation for fuzzy name matching."""
    name = name.lower()
    name = re.sub(r"\([^)]*\)", " ", name)  # drop parenthetical "(Google)" etc.
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    name = re.sub(
        r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|"
        r"holdings|group|the)\b",
        " ",
        name,
    )
    return re.sub(r"\s+", " ", name).strip()


def load_sec_index(path: str | Path = SEC_TICKERS_PATH) -> dict[str, str]:
    """Build {simplified_title: TICKER} from the SEC file, or {} if absent.

    Download once with (kept out of the repo, lives under data/raw/):
        curl -o data/raw/sec_company_tickers.json \\
             https://www.sec.gov/files/company_tickers.json
    """
    path = Path(path)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    index: dict[str, str] = {}
    for row in data.values():
        title = _simplify(row.get("title", ""))
        ticker = (row.get("ticker") or "").upper()
        if title and ticker:
            index.setdefault(title, ticker)
    return index


def enrich(mention: Mention, sec_index: dict[str, str] | None = None) -> Mention:
    """Supplement a mention's ticker from the SEC index when missing."""
    if mention.ticker_if_public:
        return mention
    if mention.company_status == "private":
        return mention  # legitimately has no ticker
    if not sec_index:
        return mention

    key = _simplify(mention.normalized_company_name)
    ticker = sec_index.get(key)
    if not ticker:
        # try the raw mention text as a fallback
        ticker = sec_index.get(_simplify(mention.mentioned_company_raw))
    if ticker:
        mention.ticker_if_public = ticker
        mention.exchange_if_public = mention.exchange_if_public or "US (SEC)"
        if mention.company_status == "unknown":
            mention.company_status = "public"
        _note(mention, f"ticker {ticker} resolved via SEC company_tickers.json")
    return mention


def _note(mention: Mention, text: str) -> None:
    mention.notes = f"{mention.notes} | {text}".strip(" |") if mention.notes else text
