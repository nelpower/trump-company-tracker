"""Heuristic enrichment: theme tags, policy angle, sentiment, relevance &
confidence scores, and bilingual one-line summaries.

These are transparent keyword/rule heuristics, NOT a model. They give a
consistent first pass that an analyst can override (via ``source['overrides']``
or by editing the JSONL). Every rule here is documented so the output is
auditable.
"""
from __future__ import annotations

import re

from src.config import SOURCE_QUALITY_RANK
from src.models import Mention

# --------------------------------------------------------------------------- #
# Keyword tables
# --------------------------------------------------------------------------- #
# Each theme -> list of regex fragments (matched case-insensitively).
THEME_KEYWORDS: dict[str, list[str]] = {
    "AI": [r"\bA\.?I\.?\b", r"artificial intelligence", r"machine learning"],
    "data_center": [r"data\s*cent(?:er|re)s?", r"hyperscal"],
    "defense": [r"defen[sc]e", r"military", r"missile", r"warfighter",
                r"national guard", r"army|navy|air force"],
    "energy": [r"energy", r"electric(?:ity)?", r"power\s+(?:plant|grid)",
               r"\bgrid\b", r"nuclear", r"\boil\b", r"natural gas", r"\bLNG\b",
               r"drill"],
    "manufacturing": [r"manufactur", r"factor(?:y|ies)", r"\bplant\b",
                      r"\bplants\b", r"reshor", r"on[- ]?shor", r"assembl",
                      r"fabricat", r"made in (?:america|the usa|the u\.s)"],
    "semiconductor": [r"semiconductor", r"\bchips?\b", r"\bfab\b", r"foundry",
                      r"wafer", r"lithograph", r"\bCPUs?\b", r"\bGPUs?\b",
                      r"processor", r"nanometer", r"chipmaker", r"chip[- ]?making"],
    "telecom": [r"telecom", r"\b5G\b", r"\b6G\b", r"broadband", r"wireless",
                r"network equipment"],
    "cloud": [r"\bcloud\b", r"software[- ]as[- ]a[- ]service", r"\bSaaS\b"],
    "auto": [r"\bauto(?:mobile|motive)?\b", r"\bcars?\b", r"\bvehicles?\b",
             r"\bEV\b", r"electric vehicle"],
    "aerospace": [r"aerospace", r"aircraft", r"\bjet\b", r"\b747\b", r"aviation",
                  r"air force one", r"\bplane\b", r"rocket", r"satellite",
                  r"\blaunch\b"],
    "infrastructure": [r"infrastructure", r"\bbridges?\b", r"\bhighways?\b",
                       r"\bports?\b"],
    "consumer": [r"\bsugar\b", r"\bsoda\b", r"\bbeverage\b", r"\biPhone\b",
                 r"\bretail\b", r"\bconsumer\b", r"\bgrocer"],
}

# Policy angle -> regex fragments. Order = priority (first match wins).
POLICY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("government_contract", [r"\bcontract", r"air force one", r"procure",
                             r"\border\b", r"\bawarded?\b"]),
    ("national_security", [r"national security", r"security agreement",
                           r"controlled by the usa", r"foreign (?:company|"
                           r"adversary|ownership)", r"cfius", r"golden share"]),
    ("export_control", [r"export control", r"export restriction",
                        r"approved customers", r"sell .* chips? .* china",
                        r"entity list"]),
    ("tariff", [r"tariffs?", r"\bduties\b", r"\blevy\b"]),
    ("manufacturing_reshoring", [r"reshor", r"on[- ]?shor", r"bring(?:ing)? "
                                 r"(?:it|them|jobs|production|manufacturing) "
                                 r"back",
                                 r"invest(?:ing|ment|ed)?\b[^.]*\bin the united states",
                                 r"invest(?:ing|ment|ed)?\b[^.]*\bin america",
                                 r"build .* in (?:america|the united states)",
                                 r"new (?:plant|factory|fabrication)"]),
    ("defense_spending", [r"defen[sc]e (?:spending|budget)", r"military budget",
                          r"rebuild .* military"]),
    ("buy_american", [r"buy american", r"made in america", r"made in the usa",
                      r"american[- ]made"]),
    ("tax_credit", [r"tax credit", r"tax break", r"\bsubsid", r"chips act",
                    r"incentive"]),
    ("deregulation", [r"deregulat", r"red tape", r"cut .* regulation",
                      r"roll back .* regulation"]),
]

POSITIVE_WORDS = [
    r"great", r"incredible", r"tremendous", r"\bbest\b", r"\blove\b", r"record",
    r"historic", r"powerful", r"fantastic", r"amazing", r"thank you", r"bullish",
    r"\bstrong\b", r"\bbig\b win", r"\bsmart\b", r"genius", r"\bup\b \d", r"\bup \d+%",
    r"wonderful", r"beautiful", r"proud",
]
NEGATIVE_WORDS = [
    r"disaster", r"terrible", r"out of control", r"\bcancel\b", r"\bbad\b",
    r"failing", r"ripping (?:us )?off", r"unfair", r"totally against", r"horrible",
    r"disgrace", r"\bsad\b", r"\bweak\b", r"\brip[- ]?off\b", r"\bripped\b",
    r"\bcheat", r"\bsteal", r"\bdumb\b", r"\bstupid\b",
]

# Themes/policies that, on their own, justify the top relevance score.
HIGH_IMPACT_THEMES = {
    "AI", "data_center", "defense", "energy", "manufacturing",
    "semiconductor", "telecom", "aerospace", "infrastructure",
}
STRONG_POLICIES = {
    "government_contract", "tariff", "national_security",
    "manufacturing_reshoring", "export_control", "defense_spending",
    "tax_credit",
}

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _matches(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _count(text: str, patterns: list[str]) -> int:
    return sum(1 for p in patterns if re.search(p, text, re.IGNORECASE))


def _context(mention: Mention) -> str:
    return " ".join(
        [
            mention.quote_context_before,
            mention.exact_quote,
            mention.quote_context_after,
        ]
    )


# --------------------------------------------------------------------------- #
# Public detectors
# --------------------------------------------------------------------------- #
def detect_themes(text: str, seed_themes: list[str] | None = None) -> list[str]:
    found = set(seed_themes or [])
    for theme, patterns in THEME_KEYWORDS.items():
        if _matches(text, patterns):
            found.add(theme)
    if not found:
        return ["other"]
    # keep canonical order
    from src.config import THEME_TAGS

    ordered = [t for t in THEME_TAGS if t in found]
    return ordered or ["other"]


def detect_policy_angle(text: str) -> str:
    for angle, patterns in POLICY_KEYWORDS:
        if _matches(text, patterns):
            return angle
    return "unknown"


def detect_sentiment(text: str) -> str:
    pos = _count(text, POSITIVE_WORDS)
    neg = _count(text, NEGATIVE_WORDS)
    if pos and neg:
        return "mixed"
    if pos:
        return "positive"
    if neg:
        return "negative"
    return "neutral"


def score_investment_relevance(mention: Mention) -> int:
    """Implements the rubric from the project spec (5 = strongest signal)."""
    themes = set(mention.theme_tags)
    high_theme = bool(themes & HIGH_IMPACT_THEMES)
    strong_policy = mention.policy_angle in STRONG_POLICIES
    sentiment = mention.sentiment_toward_company

    if strong_policy or high_theme:
        # named company + (critical sector OR concrete policy lever)
        score = 5
    else:
        # No structural signal: fall back to sentiment / casualness.
        only_soft = themes.issubset({"consumer", "other"})
        if only_soft and mention.policy_angle == "unknown":
            # brand-level remark
            score = 3 if sentiment in ("positive", "negative", "mixed") else 2
        elif sentiment in ("positive", "negative", "mixed"):
            score = 4
        else:
            score = 3

    # A sentence naming many companies is a name-drop list, not focused
    # commentary about any one of them — its themes/policy are also unreliable
    # (cross-contaminated), so cap the relevance.
    if getattr(mention, "companies_in_quote", 1) >= 4:
        score = min(score, 3)
    return score


def score_confidence(mention: Mention, source: dict | None = None) -> int:
    """Confidence the quote is genuinely Trump's words, 1-5."""
    base = {4: 5, 3: 4, 2: 3, 1: 2}.get(
        SOURCE_QUALITY_RANK.get(mention.source_quality, 2), 3
    )
    # Rule: if the quote may not be Trump's verbatim words, cap at 3.
    if source and source.get("quote_uncertain"):
        base = min(base, 3)
    # News paraphrase risk: a 'news' source without an explicit verbatim flag
    # should not claim top confidence.
    if mention.source_type == "news" and not (source or {}).get("verbatim_quote"):
        base = min(base, 3)
    if (mention.speaker or "").strip().lower() not in (
        "donald j. trump",
        "donald trump",
        "trump",
    ):
        base = min(base, 3)
    return max(1, min(5, base))


# --------------------------------------------------------------------------- #
# Summaries
# --------------------------------------------------------------------------- #
_SENTI_ZH = {"positive": "正面", "negative": "负面", "neutral": "中性", "mixed": "褒贬不一"}
_POLICY_ZH = {
    "government_contract": "政府采购/合同",
    "tariff": "关税",
    "buy_american": "买美国货",
    "national_security": "国家安全",
    "manufacturing_reshoring": "制造业回流",
    "deregulation": "放松管制",
    "export_control": "出口管制",
    "defense_spending": "国防开支",
    "tax_credit": "税收抵免/补贴",
    "unknown": "政策含义不明确",
}
_TYPE_ZH = {
    "white_house": "白宫官方讲话",
    "social_media": "社交媒体发帖",
    "video_transcript": "视频转写",
    "news": "新闻报道引语",
    "company_release": "公司新闻稿引语",
    "other": "其他来源",
}


def _short(text: str, n: int = 140) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def make_summaries(mention: Mention) -> tuple[str, str]:
    ticker = f"，{mention.ticker_if_public}" if mention.ticker_if_public else ""
    zh = (
        f"{mention.date or '日期不详'}，特朗普在{_TYPE_ZH.get(mention.source_type, '某来源')}"
        f"中{_SENTI_ZH.get(mention.sentiment_toward_company, '中性')}提及"
        f"{mention.normalized_company_name}{ticker}；政策角度：{_POLICY_ZH.get(mention.policy_angle, '不明确')}"
        f"，主题：{'/'.join(mention.theme_tags)}。原话：「{_short(mention.exact_quote)}」"
        f"（投资相关性 {mention.investment_relevance_score}/5）。"
    )
    en = (
        f"On {mention.date or 'n/a'}, Trump made a "
        f"{mention.sentiment_toward_company} reference to "
        f"{mention.normalized_company_name}"
        f"{(' (' + mention.ticker_if_public + ')') if mention.ticker_if_public else ''} "
        f"via {mention.source_type.replace('_', ' ')}. "
        f"Policy angle: {mention.policy_angle.replace('_', ' ')}; "
        f"themes: {', '.join(mention.theme_tags)}. "
        f"Quote: \"{_short(mention.exact_quote)}\" "
        f"(investment relevance {mention.investment_relevance_score}/5)."
    )
    return zh, en


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def enrich_scoring(mention: Mention, source: dict | None = None) -> Mention:
    """Fill every heuristic field, respecting values already set by overrides."""
    ctx = _context(mention)
    overrides = (source or {}).get("overrides") or {}
    preset_all = overrides.get("_all_") or {}
    preset_co = overrides.get(mention.normalized_company_name) or {}

    def is_preset(key: str) -> bool:
        return key in preset_all or key in preset_co

    if not is_preset("theme_tags"):
        mention.theme_tags = detect_themes(ctx, mention.theme_tags)
    if not is_preset("policy_angle"):
        mention.policy_angle = detect_policy_angle(ctx)
    if not is_preset("sentiment_toward_company"):
        mention.sentiment_toward_company = detect_sentiment(ctx)
    if not is_preset("investment_relevance_score"):
        mention.investment_relevance_score = score_investment_relevance(mention)
    if not is_preset("confidence_score"):
        mention.confidence_score = score_confidence(mention, source)

    # Summaries always regenerated from the (now final) fields.
    mention.summary_zh, mention.summary_en = make_summaries(mention)
    return mention
