"""Tests for theme/policy/sentiment detection and relevance/confidence scoring."""
import pytest

from src.models import Mention
from src.score_relevance import (
    detect_policy_angle,
    detect_sentiment,
    detect_themes,
    enrich_scoring,
    score_confidence,
    score_investment_relevance,
)


# ----- theme detection ----------------------------------------------------- #
@pytest.mark.parametrize(
    "text, expected_theme",
    [
        ("They will build a new semiconductor fab.", "semiconductor"),
        ("A massive data center in Texas.", "data_center"),
        ("Boeing 747 Air Force One program.", "aerospace"),
        ("Tariffs on the auto industry and cars.", "auto"),
        ("Using real cane sugar in the drink.", "consumer"),
    ],
)
def test_detect_themes(text, expected_theme):
    assert expected_theme in detect_themes(text)


def test_detect_themes_defaults_to_other():
    assert detect_themes("A perfectly generic sentence.") == ["other"]


# ----- policy detection ---------------------------------------------------- #
@pytest.mark.parametrize(
    "text, expected",
    [
        ("We will put tariffs on imports.", "tariff"),
        ("Cancel the Air Force One contract.", "government_contract"),
        ("Bought by a foreign company, a national security risk.",
         "national_security"),
        ("Investing $100 billion in the United States.",
         "manufacturing_reshoring"),
        ("Allowing chip sales to approved customers via export control.",
         "export_control"),
        ("A nice day in Florida.", "unknown"),
    ],
)
def test_detect_policy_angle(text, expected):
    assert detect_policy_angle(text) == expected


# ----- sentiment detection ------------------------------------------------- #
def test_detect_sentiment():
    assert detect_sentiment("This is a tremendous, incredible, record deal.") == "positive"
    assert detect_sentiment("It is a total disaster and out of control.") == "negative"
    assert detect_sentiment("The once great company is a disaster now.") == "mixed"
    assert detect_sentiment("They announced it on Tuesday.") == "neutral"


# ----- investment relevance rubric ----------------------------------------- #
def _m(themes, policy="unknown", sentiment="neutral") -> Mention:
    return Mention(
        theme_tags=list(themes),
        policy_angle=policy,
        sentiment_toward_company=sentiment,
    )


def test_score5_strong_policy_and_high_theme():
    m = _m(["semiconductor", "manufacturing"], "manufacturing_reshoring", "positive")
    assert score_investment_relevance(m) == 5


def test_score5_high_theme_alone():
    m = _m(["defense"], "unknown", "neutral")
    assert score_investment_relevance(m) == 5


def test_score5_strong_policy_alone():
    m = _m(["consumer"], "tariff", "neutral")
    assert score_investment_relevance(m) == 5


def test_score4_soft_theme_with_sentiment():
    # cloud is neither "high-impact" nor a soft consumer remark
    m = _m(["cloud"], "unknown", "positive")
    assert score_investment_relevance(m) == 4


def test_score3_brand_remark_with_sentiment():
    m = _m(["consumer"], "unknown", "positive")
    assert score_investment_relevance(m) == 3


def test_score2_casual_neutral_brand_remark():
    m = _m(["consumer"], "unknown", "neutral")
    assert score_investment_relevance(m) == 2


def test_namedrop_list_caps_relevance():
    # Would be 5 (semiconductor + tariff), but it's a list of many companies.
    m = _m(["semiconductor"], "tariff", "positive")
    m.companies_in_quote = 6
    assert score_investment_relevance(m) == 3


# ----- confidence ---------------------------------------------------------- #
def test_confidence_official_is_max():
    m = Mention(source_type="white_house", source_quality="official",
                speaker="Donald J. Trump")
    assert score_confidence(m) == 5


def test_confidence_news_paraphrase_is_capped():
    m = Mention(source_type="news", source_quality="high",
                speaker="Donald J. Trump")
    # no verbatim flag -> capped at 3
    assert score_confidence(m, source={}) == 3
    # explicit verbatim flag -> not capped
    assert score_confidence(m, source={"verbatim_quote": True}) == 4


def test_confidence_uncertain_quote_capped():
    m = Mention(source_type="social_media", source_quality="official",
                speaker="Donald J. Trump")
    assert score_confidence(m, source={"quote_uncertain": True}) == 3


def test_confidence_non_trump_speaker_capped():
    m = Mention(source_type="white_house", source_quality="official",
                speaker="Tim Cook")
    assert score_confidence(m) <= 3


# ----- enrich end-to-end --------------------------------------------------- #
def test_enrich_scoring_fills_all_fields():
    m = Mention(
        date="2025-03-03",
        normalized_company_name="Taiwan Semiconductor Manufacturing Company (TSMC)",
        ticker_if_public="TSM",
        source_type="white_house",
        source_quality="official",
        theme_tags=["semiconductor", "manufacturing"],
        exact_quote=("Taiwan Semiconductor will invest at least $100 billion in "
                     "the United States to build semiconductor facilities."),
    )
    enrich_scoring(m, source={"verbatim_quote": True})
    assert m.policy_angle == "manufacturing_reshoring"
    assert m.investment_relevance_score == 5
    assert m.confidence_score == 5
    assert m.summary_zh and m.summary_en
    assert "TSM" in m.summary_zh


def test_overrides_are_respected():
    m = Mention(
        date="2025-01-01",
        normalized_company_name="Apple Inc.",
        theme_tags=["consumer"],
        exact_quote="Apple is fine.",
    )
    src = {"overrides": {"Apple Inc.": {"sentiment_toward_company": "negative",
                                        "investment_relevance_score": 5}}}
    # simulate extraction having applied overrides already:
    m.sentiment_toward_company = "negative"
    m.investment_relevance_score = 5
    enrich_scoring(m, source=src)
    assert m.sentiment_toward_company == "negative"  # not overwritten by heuristic
    assert m.investment_relevance_score == 5
