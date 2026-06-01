"""Tests for the curated Trump trades loader."""
from src.trades import Trade, load_trades


def test_load_trades_basic():
    ts = load_trades()
    assert ts and all(isinstance(t, Trade) for t in ts)
    tickers = {t.ticker for t in ts}
    assert {"DELL", "AAPL", "MU", "PLTR", "NVDA"} <= tickers


def test_trade_fields_parsed():
    ts = load_trades()
    dell = next(t for t in ts if t.ticker == "DELL")
    assert dell.action == "buy"
    assert dell.date == "2026-02-10"          # YAML date coerced to ISO string
    assert dell.amount and dell.company == "Dell Technologies Inc."
    pltr = next(t for t in ts if t.ticker == "PLTR")
    assert pltr.action == "sell"


def test_trades_sorted_newest_first():
    ts = load_trades()
    assert all(ts[i].date >= ts[i + 1].date for i in range(len(ts) - 1))
