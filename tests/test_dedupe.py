"""Tests for de-duplication across sources."""
from src.dedupe import dedupe, quote_similarity
from src.models import Mention


def _m(quote, company="Apple Inc.", date="2025-03-03", quality="high",
       title="src", url="http://x", conf=4) -> Mention:
    m = Mention(
        date=date,
        normalized_company_name=company,
        exact_quote=quote,
        source_quality=quality,
        source_title=title,
        source_url=url,
        confidence_score=conf,
    )
    m.ensure_id()
    return m


def test_quote_similarity_bounds():
    assert quote_similarity("hello world", "hello world") == 1.0
    assert quote_similarity("hello world", "completely different text") < 0.5


def test_exact_duplicates_collapse():
    a = _m("Apple will invest 500 billion in the United States.")
    b = _m("Apple will invest 500 billion in the United States.")  # identical
    out = dedupe([a, b])
    assert len(out) == 1


def test_fuzzy_merge_keeps_highest_quality_source():
    official = _m(
        "Taiwan Semiconductor will invest at least $100 billion in the "
        "United States to build semiconductor facilities.",
        company="TSMC", quality="official", title="White House", conf=5,
    )
    news = _m(
        "Taiwan Semiconductor will invest at least $100 billion in the United "
        "States to build state-of-the-art semiconductor facilities.",
        company="TSMC", quality="high", title="CBS News",
        url="http://cbs", conf=4,
    )
    out = dedupe([news, official])  # order shouldn't matter
    assert len(out) == 1
    winner = out[0]
    assert winner.source_quality == "official"
    assert winner.source_title == "White House"
    # provenance of the losing source is preserved
    assert "CBS News" in winner.notes


def test_different_companies_not_merged():
    a = _m("Great investment news today.", company="Apple Inc.")
    b = _m("Great investment news today.", company="NVIDIA Corporation")
    out = dedupe([a, b])
    assert len(out) == 2


def test_different_quotes_same_company_not_merged():
    a = _m("Apple announced a record 500 billion dollar investment in America.")
    b = _m("Boeing costs are out of control, cancel the order entirely.")
    out = dedupe([a, b])  # same company+date but dissimilar quotes
    assert len(out) == 2


def test_dedupe_is_idempotent():
    a = _m("Apple will invest 500 billion in the United States.")
    once = dedupe([a, a, a])
    twice = dedupe(once + [a])
    assert len(once) == 1
    assert len(twice) == 1
    assert once[0].id == twice[0].id
