"""Load Trump's curated personal stock trades (from OGE Form 278-T disclosures).

Amounts are disclosed RANGES, not exact figures. This is a curated AI-relevant
subset; see data/trump_trades.yaml.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, fields

from src.config import DATA_DIR, load_yaml

TRADES_PATH = DATA_DIR / "trump_trades.yaml"


@dataclass
class Trade:
    date: str
    ticker: str
    company: str
    action: str = "buy"        # buy | sell
    amount: str = ""           # disclosed range label, e.g. "$1M–$5M"
    note: str = ""
    source_url: str = ""
    unsolicited: bool = False
    date_note: str = ""        # set when only the month/quarter is known

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def load_trades(path=TRADES_PATH) -> list[Trade]:
    data = load_yaml(path)
    known = {f.name for f in fields(Trade)}
    out: list[Trade] = []
    for t in (data.get("trades", []) if isinstance(data, dict) else []):
        d = dict(t)
        if d.get("date") and isinstance(d["date"], (dt.date, dt.datetime)):
            d["date"] = d["date"].isoformat()[:10]
        out.append(Trade(**{k: v for k, v in d.items() if k in known}))
    out.sort(key=lambda x: x.date, reverse=True)   # newest first
    return out
