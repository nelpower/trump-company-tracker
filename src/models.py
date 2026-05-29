"""The :class:`Mention` record — one Trump statement about one company."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, fields
from typing import Any

from src.config import DEFAULT_SPEAKER, FIELDNAMES


def _norm_for_id(text: str) -> str:
    """Normalise a string so that trivial whitespace/case differences in a
    quote do not produce two different IDs for what is the same record."""
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def compute_id(date: str, normalized_company: str, exact_quote: str) -> str:
    """Deterministic short id from the fields that define record identity.

    Re-running the pipeline on the same input therefore produces the same id,
    which is what keeps the output idempotent (no duplicate rows).
    """
    payload = "|".join(
        [
            (date or "").strip(),
            _norm_for_id(normalized_company),
            _norm_for_id(exact_quote),
        ]
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


@dataclass
class Mention:
    """A single (statement, company) pair. Fields mirror :data:`FIELDNAMES`."""

    date: str = ""
    speaker: str = DEFAULT_SPEAKER
    source_title: str = ""
    source_url: str = ""
    source_type: str = "other"
    source_quality: str = "medium"
    exact_quote: str = ""
    quote_context_before: str = ""
    quote_context_after: str = ""
    mentioned_company_raw: str = ""
    normalized_company_name: str = ""
    ticker_if_public: str = ""
    exchange_if_public: str = ""
    company_status: str = "unknown"
    sector: str = ""
    theme_tags: list[str] = field(default_factory=list)
    sentiment_toward_company: str = "neutral"
    policy_angle: str = "unknown"
    investment_relevance_score: int = 1
    summary_zh: str = ""
    summary_en: str = ""
    confidence_score: int = 1
    notes: str = ""
    id: str = ""
    # Internal (not serialized): how many distinct companies share the quote
    # sentence. A high count means a name-drop list, not focused commentary.
    companies_in_quote: int = 1

    def ensure_id(self) -> str:
        """Populate :attr:`id` from the identity fields if not already set."""
        if not self.id:
            self.id = compute_id(
                self.date, self.normalized_company_name, self.exact_quote
            )
        return self.id

    # ----- serialisation ---------------------------------------------------- #
    def to_json_obj(self) -> dict[str, Any]:
        """JSONL-friendly dict (``theme_tags`` stays a list)."""
        self.ensure_id()
        return {name: getattr(self, name) for name in FIELDNAMES}

    def to_csv_row(self) -> dict[str, str]:
        """CSV-friendly dict (lists joined with ``|``, ints stringified)."""
        obj = self.to_json_obj()
        row: dict[str, str] = {}
        for key, value in obj.items():
            if isinstance(value, list):
                row[key] = "|".join(str(v) for v in value)
            else:
                row[key] = "" if value is None else str(value)
        return row

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Mention":
        """Build a Mention from a dict (CSV row or JSON obj), coercing types."""
        known = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key not in known:
                continue
            if key == "theme_tags" and isinstance(value, str):
                value = [t for t in value.split("|") if t]
            elif key in ("investment_relevance_score", "confidence_score"):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = 1
            kwargs[key] = value
        m = cls(**kwargs)
        m.ensure_id()
        return m
