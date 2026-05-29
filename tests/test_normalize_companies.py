"""Tests for company identification / normalization."""
import pytest

from src.extract_mentions import extract_from_source, split_sentences
from src.normalize_companies import CompanyResolver


@pytest.fixture(scope="module")
def resolver() -> CompanyResolver:
    # Uses the real data/company_aliases.yaml and data/blacklist.yaml.
    return CompanyResolver()


# ----- alias normalization ------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Dell", "Dell Technologies Inc."),
        ("Dell Computer", "Dell Technologies Inc."),
        ("Dell Technologies", "Dell Technologies Inc."),
        ("Google", "Alphabet Inc. (Google)"),
        ("Alphabet", "Alphabet Inc. (Google)"),
        ("Nvidia", "NVIDIA Corporation"),
        ("Taiwan Semiconductor", "Taiwan Semiconductor Manufacturing Company (TSMC)"),
        ("TSMC", "Taiwan Semiconductor Manufacturing Company (TSMC)"),
    ],
)
def test_alias_resolves_to_canonical(resolver, raw, expected):
    info = resolver.resolve(raw)
    assert info is not None
    assert info.normalized == expected


def test_hp_inc_and_hpe_are_distinct(resolver):
    hp = resolver.resolve("HP Inc.")
    hpe = resolver.resolve("HPE")
    assert hp is not None and hpe is not None
    assert hp.ticker == "HPQ"
    assert hpe.ticker == "HPE"
    assert hp.normalized != hpe.normalized
    # "Hewlett Packard Enterprise" must map to HPE, not HP Inc.
    assert resolver.resolve("Hewlett Packard Enterprise").ticker == "HPE"


def test_ticker_is_correct(resolver):
    assert resolver.resolve("Apple").ticker == "AAPL"
    assert resolver.resolve("Boeing").ticker == "BA"
    assert resolver.resolve("U.S. Steel").ticker == "X"


def test_private_company_has_no_ticker(resolver):
    info = resolver.resolve("OpenAI")
    assert info is not None
    assert info.status == "private"
    assert info.ticker == ""


# ----- blacklist (false-positive guard) ------------------------------------ #
@pytest.mark.parametrize("term", ["America", "United States", "White House",
                                  "Truth", "China", "Congress", "the Fed"])
def test_blacklisted_terms_are_not_companies(resolver, term):
    assert resolver.is_blacklisted(term)
    assert resolver.resolve(term) is None


def test_blacklist_excluded_from_text_search(resolver):
    hits = resolver.find_known_mentions("America will win and the White House agrees.")
    assert hits == []


# ----- in-text matching ---------------------------------------------------- #
def test_find_multiple_companies(resolver):
    hits = resolver.find_known_mentions("I use a Dell laptop and an Apple phone.")
    names = sorted(h.info.normalized for h in hits)
    assert names == ["Apple Inc.", "Dell Technologies Inc."]


def test_longest_alias_wins(resolver):
    hits = resolver.find_known_mentions("Hewlett Packard Enterprise raised guidance.")
    assert len(hits) == 1
    assert hits[0].info.ticker == "HPE"


def test_dotted_name_us_steel(resolver):
    hits = resolver.find_known_mentions("He moved to block U.S. Steel from the sale.")
    assert any(h.info.normalized == "United States Steel Corporation" for h in hits)


def test_word_boundary_no_false_substring(resolver):
    # "Forditor" must not match "Ford"; "Intelligence" must not match "Intel".
    hits = resolver.find_known_mentions("Artificial Intelligence is not Intel.")
    names = {h.info.normalized for h in hits}
    assert "Intel Corporation" in names  # the standalone "Intel" should match
    # but the word inside "Intelligence" should not have produced a 2nd hit
    assert len([h for h in hits if h.info.normalized == "Intel Corporation"]) == 1


# ----- extraction end-to-end ----------------------------------------------- #
def test_two_companies_in_one_quote(resolver):
    source = {
        "id": "t1",
        "date": "2024-12-02",
        "source_type": "social_media",
        "source_quality": "high",
        "text": ("I am totally against the once great and powerful U.S. Steel "
                 "being bought by a foreign company, in this case Nippon Steel "
                 "of Japan."),
    }
    mentions = extract_from_source(source, resolver)
    names = sorted(m.normalized_company_name for m in mentions)
    assert names == ["Nippon Steel Corporation",
                     "United States Steel Corporation"]
    # both records carry the full verbatim sentence as the quote
    for m in mentions:
        assert "U.S. Steel" in m.exact_quote and "Nippon Steel" in m.exact_quote


def test_one_record_per_company_per_source(resolver):
    # Company mentioned in two sentences -> a single record, extra folded to notes.
    source = {
        "id": "t2",
        "date": "2025-02-24",
        "source_type": "social_media",
        "source_quality": "high",
        "text": "Apple announced a big investment. Thank you Apple!",
    }
    mentions = extract_from_source(source, resolver)
    assert len(mentions) == 1
    assert mentions[0].normalized_company_name == "Apple Inc."
    assert "also mentions" in mentions[0].notes.lower()


def test_split_sentences_protects_abbreviations():
    sents = split_sentences("He backed U.S. Steel. Then he left.")
    assert sents == ["He backed U.S. Steel.", "Then he left."]


# ----- precision filters (false-positive guards) --------------------------- #
def test_ambiguous_alias_requires_capital(resolver):
    # lowercase "intel" = intelligence, must NOT match the company
    assert resolver.find_known_mentions("US intel flagged election risks.") == []
    # capitalised "Intel" = the company, must match
    hits = resolver.find_known_mentions("Congratulations to Intel on a great job.")
    assert any(h.info.normalized == "Intel Corporation" for h in hits)


def test_match_inside_url_is_dropped(resolver):
    assert resolver.find_known_mentions(
        "Buy it at https://www.amazon.com/dp/123 today"
    ) == []


def test_suppress_context_whole_post(resolver):
    info = resolver.resolve("Amazon")
    book = "Her memoir is a MUST READ, available on Amazon and in every bookstore."
    real = "Amazon will invest $50B to build AI data centers for the government."
    assert resolver.is_suppressed(info, book) is True
    assert resolver.is_suppressed(info, real) is False


def test_book_keyword_does_not_match_facebook(resolver):
    info = resolver.resolve("Amazon")
    assert resolver.is_suppressed(info, "Amazon and Facebook are rivals.") is False


def test_theme_tags_come_from_content_not_sector(resolver):
    from src.score_relevance import enrich_scoring
    src = {"id": "d", "date": "2025-12-02", "source_type": "social_media",
           "source_quality": "high", "text": "I LOVE DELL!!!"}
    ms = extract_from_source(src, resolver)
    assert len(ms) == 1
    enrich_scoring(ms[0], src)
    # a casual cheer must not inherit Dell's 'manufacturing' sector tag...
    assert "manufacturing" not in ms[0].theme_tags
    # ...nor be inflated to a top relevance score
    assert ms[0].investment_relevance_score <= 3


def test_semiconductor_content_scores_high(resolver):
    from src.score_relevance import enrich_scoring
    src = {"id": "i", "date": "2026-01-08", "source_type": "social_media",
           "source_quality": "high",
           "text": "Intel just launched the first sub 2 nanometer CPU processor."}
    ms = extract_from_source(src, resolver)
    intel = [m for m in ms if m.normalized_company_name == "Intel Corporation"][0]
    enrich_scoring(intel, src)
    assert "semiconductor" in intel.theme_tags
    assert intel.investment_relevance_score == 5
