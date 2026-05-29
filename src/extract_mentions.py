"""Turn a source's text into :class:`Mention` records.

For each source we split the text into sentences, find company mentions, and
emit **one record per (source, company)** — the most informative sentence
becomes the ``exact_quote`` and any other sentences mentioning the same company
are folded into ``notes``. This avoids spamming several near-identical rows for
the same statement.
"""
from __future__ import annotations

import re

from src.config import DEFAULT_SPEAKER
from src.models import Mention
from src.normalize_companies import CompanyResolver

# Abbreviations whose trailing period must NOT end a sentence.
_ABBREV = [
    "U.S.A.", "U.S.", "U.K.", "U. S.", "D.C.", "Inc.", "Corp.", "Co.", "Ltd.",
    "Mr.", "Mrs.", "Ms.", "Dr.", "Jr.", "Sr.", "St.", "vs.", "No.", "Sen.",
    "Rep.", "Gov.", "Gen.", "Lt.", "Ph.D.", "a.m.", "p.m.",
]
_PLACEHOLDER = ""  # stand-in for a protected period during splitting


def split_sentences(text: str) -> list[str]:
    """Lightweight sentence splitter that protects common abbreviations and
    handles ALL-CAPS social posts. Good enough for short remarks/posts; for
    long messy transcripts a real model (spaCy/nltk) would do better."""
    if not text:
        return []
    text = text.replace("\r\n", "\n").strip()

    protected = text
    for abbr in _ABBREV:
        protected = protected.replace(abbr, abbr.replace(".", _PLACEHOLDER))

    # Split on ., !, ? (one or more) followed by whitespace and a likely
    # sentence start (capital letter, quote, or digit). Also split on blank
    # lines so list-like transcripts break apart.
    parts = re.split(r'(?<=[.!?])["”\')\]]?\s+(?=[A-Z0-9"“\'(])', protected)
    sentences: list[str] = []
    for part in parts:
        for chunk in part.split("\n"):
            chunk = chunk.replace(_PLACEHOLDER, ".").strip()
            if chunk:
                sentences.append(chunk)
    return sentences


def extract_from_source(source: dict, resolver: CompanyResolver) -> list[Mention]:
    """Extract mentions from one source dict (which must carry a ``text`` key)."""
    text = (source.get("text") or "").strip()
    if not text:
        return []

    sentences = split_sentences(text)
    # company normalized name -> list of (sentence_index, hit)
    by_company: dict[str, list[tuple[int, object]]] = {}
    # sentence index -> set of companies sharing it (to detect name-drop lists)
    sent_companies: dict[int, set[str]] = {}
    for idx, sent in enumerate(sentences):
        for hit in resolver.find_known_mentions(sent):
            by_company.setdefault(hit.info.normalized, []).append((idx, hit))
            sent_companies.setdefault(idx, set()).add(hit.info.normalized)

    mentions: list[Mention] = []
    for normalized, occurrences in by_company.items():
        # primary occurrence = longest sentence (most context / signal)
        primary_idx, primary_hit = max(
            occurrences, key=lambda pair: len(sentences[pair[0]])
        )
        info = primary_hit.info
        # Post-level noise suppression (e.g. "Amazon" only in a book-promo post).
        if resolver.is_suppressed(info, text):
            continue
        quote = sentences[primary_idx]
        before = sentences[primary_idx - 1] if primary_idx > 0 else ""
        after = (
            sentences[primary_idx + 1]
            if primary_idx + 1 < len(sentences)
            else ""
        )

        co_count = len(sent_companies.get(primary_idx, {normalized}))

        notes_bits: list[str] = []
        if co_count >= 4:
            notes_bits.append(
                f"Name-drop list: {co_count} companies share this sentence; "
                "relevance capped (not focused commentary)."
            )
        other_idxs = sorted({i for i, _ in occurrences if i != primary_idx})
        for i in other_idxs:
            notes_bits.append(f"Same source also mentions company: \"{sentences[i]}\"")

        m = Mention(
            date=str(source.get("date", "")).strip(),
            speaker=source.get("speaker", DEFAULT_SPEAKER),
            source_title=source.get("title", ""),
            source_url=source.get("url", ""),
            source_type=source.get("source_type", "other"),
            source_quality=source.get("source_quality", "medium"),
            exact_quote=quote,
            quote_context_before=before,
            quote_context_after=after,
            mentioned_company_raw=primary_hit.raw,
            normalized_company_name=info.normalized,
            ticker_if_public=info.ticker,
            exchange_if_public=info.exchange,
            company_status=info.status,
            sector=info.sector,
            # theme_tags reflect the STATEMENT's topic (filled from the quote's
            # content by score_relevance), NOT the company's static sector — so
            # a casual "I love Dell!" isn't tagged 'manufacturing' and inflated.
            theme_tags=[],
            notes=" | ".join(notes_bits),
            companies_in_quote=co_count,
        )
        # Allow a source to pre-set / override heuristic fields (e.g. a curated
        # sentiment). Anything in source["overrides"] keyed by company applies.
        _apply_overrides(m, source, normalized)
        m.ensure_id()
        mentions.append(m)

    # Optional: surface unknown ORGs discovered by spaCy for human review.
    if resolver.has_spacy:
        mentions.extend(_discover_unknown(source, sentences, resolver))

    return mentions


def _apply_overrides(m: Mention, source: dict, normalized: str) -> None:
    overrides = source.get("overrides") or {}
    # global overrides apply to all companies in the source
    for key in ("sentiment_toward_company", "policy_angle",
                "investment_relevance_score", "confidence_score", "notes"):
        if key in (overrides.get("_all_") or {}):
            setattr(m, key, overrides["_all_"][key])
    # per-company overrides win
    for key, value in (overrides.get(normalized) or {}).items():
        if hasattr(m, key):
            setattr(m, key, value)


def _discover_unknown(
    source: dict, sentences: list[str], resolver: CompanyResolver
) -> list[Mention]:
    out: list[Mention] = []
    seen: set[str] = set()
    for idx, sent in enumerate(sentences):
        for raw in resolver.discover_org_candidates(sent):
            if raw in seen:
                continue
            seen.add(raw)
            before = sentences[idx - 1] if idx > 0 else ""
            after = sentences[idx + 1] if idx + 1 < len(sentences) else ""
            m = Mention(
                date=str(source.get("date", "")).strip(),
                speaker=source.get("speaker", DEFAULT_SPEAKER),
                source_title=source.get("title", ""),
                source_url=source.get("url", ""),
                source_type=source.get("source_type", "other"),
                source_quality=source.get("source_quality", "medium"),
                exact_quote=sent,
                quote_context_before=before,
                quote_context_after=after,
                mentioned_company_raw=raw,
                normalized_company_name=raw,
                company_status="unknown",
                theme_tags=["other"],
                notes="spaCy-discovered ORG, not in alias table — needs review.",
            )
            m.ensure_id()
            out.append(m)
    return out
