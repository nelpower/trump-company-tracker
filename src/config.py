"""Central configuration: paths, schema field order, and controlled vocabularies.

Everything that other modules need to agree on lives here so the CSV/JSONL
schema and the allowed enum values have a single source of truth.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# --------------------------------------------------------------------------- #
# Paths (all relative to the project root, never to the C: drive)
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
MANUAL_TEXTS_DIR = RAW_DIR / "manual_texts"
PROCESSED_DIR = DATA_DIR / "processed"
OUTPUTS_DIR = BASE_DIR / "outputs"

SOURCES_PATH = DATA_DIR / "sources.yaml"
ALIASES_PATH = DATA_DIR / "company_aliases.yaml"
BLACKLIST_PATH = DATA_DIR / "blacklist.yaml"
# Optional: download from https://www.sec.gov/files/company_tickers.json
SEC_TICKERS_PATH = RAW_DIR / "sec_company_tickers.json"

CSV_OUT = OUTPUTS_DIR / "trump_company_mentions.csv"
JSONL_OUT = OUTPUTS_DIR / "trump_company_mentions.jsonl"
REPORT_OUT = OUTPUTS_DIR / "report.md"

# --------------------------------------------------------------------------- #
# Schema: the exact field order for CSV / JSONL output.
# --------------------------------------------------------------------------- #
FIELDNAMES: list[str] = [
    "id",
    "date",
    "speaker",
    "source_title",
    "source_url",
    "source_type",
    "source_quality",
    "exact_quote",
    "quote_context_before",
    "quote_context_after",
    "mentioned_company_raw",
    "normalized_company_name",
    "ticker_if_public",
    "exchange_if_public",
    "company_status",
    "sector",
    "theme_tags",
    "sentiment_toward_company",
    "policy_angle",
    "investment_relevance_score",
    "summary_zh",
    "summary_en",
    "confidence_score",
    "notes",
]

# --------------------------------------------------------------------------- #
# Controlled vocabularies (validated, not enforced — invalid values are kept
# but flagged so we never silently drop data).
# --------------------------------------------------------------------------- #
SOURCE_TYPES = {
    "white_house",
    "social_media",
    "video_transcript",
    "news",
    "company_release",
    "other",
}

SOURCE_QUALITY = {"official", "high", "medium", "low"}
# Higher rank wins during de-duplication.
SOURCE_QUALITY_RANK = {"official": 4, "high": 3, "medium": 2, "low": 1}

COMPANY_STATUS = {"public", "private", "subsidiary", "unknown"}

THEME_TAGS = [
    "AI",
    "data_center",
    "defense",
    "energy",
    "manufacturing",
    "semiconductor",
    "telecom",
    "cloud",
    "auto",
    "aerospace",
    "infrastructure",
    "consumer",
    "other",
]

POLICY_ANGLES = {
    "government_contract",
    "tariff",
    "buy_american",
    "national_security",
    "manufacturing_reshoring",
    "deregulation",
    "export_control",
    "defense_spending",
    "tax_credit",
    "unknown",
}

SENTIMENTS = {"positive", "negative", "neutral", "mixed"}

DEFAULT_SPEAKER = "Donald J. Trump"


def load_yaml(path: str | Path) -> Any:
    """Load a YAML file, returning ``{}`` for a missing/empty file."""
    path = Path(path)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}
