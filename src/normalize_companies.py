"""Company identification and normalization.

Two complementary strategies:

1. **Alias dictionary (primary, always on).** High-precision matching of known
   companies from ``company_aliases.yaml``. Returns ticker / exchange / sector.
2. **spaCy ORG NER (optional, off unless spaCy + a model are installed).** Used
   only to *discover* organisations not yet in the alias table. These are marked
   ``company_status = unknown`` with no ticker, for human review — we never
   invent tickers from NER output.

The :class:`CompanyResolver` is the single object the rest of the pipeline uses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from src.config import ALIASES_PATH, BLACKLIST_PATH, load_yaml


def _norm_key(text: str) -> str:
    """Lower-case and collapse internal whitespace for stable dict lookups."""
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


@dataclass
class CompanyInfo:
    normalized: str
    ticker: str = ""
    exchange: str = ""
    status: str = "unknown"
    sector: str = ""
    themes: tuple[str, ...] = ()
    # Precision controls (see company_aliases.yaml):
    ambiguous: bool = False           # alias is a common word -> require a capital
    suppress_context: tuple[str, ...] = ()  # drop if any keyword is in the sentence


def _looks_like_url(text: str, start: int, end: int) -> bool:
    """True if the match sits inside a URL / domain / handle token.

    Catches e.g. 'amazon.com/dp/...' or '.../michael-dell-donate-...'
    where the company name is part of a link, not a statement about the company.
    """
    left = start
    while left > 0 and not text[left - 1].isspace():
        left -= 1
    right = end
    while right < len(text) and not text[right].isspace():
        right += 1
    token = text[left:right].lower()
    return any(s in token for s in ("http", "www.", ".com", ".org", ".net", ".gov", "/", "@"))


@dataclass
class CompanyHit:
    """One alias match inside a piece of text."""

    raw: str          # the exact substring matched
    start: int
    end: int
    info: CompanyInfo


class CompanyResolver:
    def __init__(
        self,
        aliases_path: str | Path = ALIASES_PATH,
        blacklist_path: str | Path = BLACKLIST_PATH,
        use_spacy: bool = False,
    ) -> None:
        self._alias_index: dict[str, CompanyInfo] = {}
        self._blacklist: set[str] = set()
        self._pattern: re.Pattern[str] | None = None
        self._nlp = None  # lazy spaCy pipeline

        self._load_aliases(aliases_path)
        self._load_blacklist(blacklist_path)
        self._build_pattern()
        if use_spacy:
            self._try_load_spacy()

    # ----- loading --------------------------------------------------------- #
    def _load_aliases(self, path: str | Path) -> None:
        data = load_yaml(path)
        for entry in data.get("companies", []):
            info = CompanyInfo(
                normalized=entry["normalized"],
                ticker=entry.get("ticker", "") or "",
                exchange=entry.get("exchange", "") or "",
                status=entry.get("status", "unknown") or "unknown",
                sector=entry.get("sector", "") or "",
                themes=tuple(entry.get("themes", []) or []),
                ambiguous=bool(entry.get("ambiguous", False)),
                suppress_context=tuple(
                    s.lower() for s in (entry.get("suppress_context", []) or [])
                ),
            )
            for alias in entry.get("aliases", []):
                self._alias_index[_norm_key(alias)] = info
            # the canonical name is always matchable too
            self._alias_index.setdefault(_norm_key(entry["normalized"]), info)

    def _load_blacklist(self, path: str | Path) -> None:
        data = load_yaml(path)
        self._blacklist = {_norm_key(t) for t in data.get("blacklist", [])}

    def _build_pattern(self) -> None:
        """One big alternation of all aliases, longest first so that e.g.
        'Taiwan Semiconductor' is preferred over a hypothetical 'Taiwan'."""
        aliases = sorted(self._alias_index.keys(), key=len, reverse=True)
        pieces = []
        for alias in aliases:
            esc = re.escape(alias).replace(r"\ ", " ").replace(" ", r"\s+")
            pieces.append(esc)
        if not pieces:
            self._pattern = None
            return
        # custom boundaries that tolerate dotted names like "U.S. Steel"
        body = "|".join(pieces)
        self._pattern = re.compile(
            rf"(?<![A-Za-z0-9])(?:{body})(?![A-Za-z0-9])", re.IGNORECASE
        )

    def _try_load_spacy(self) -> None:
        try:
            import spacy  # type: ignore

            for model in ("en_core_web_trf", "en_core_web_md", "en_core_web_sm"):
                try:
                    self._nlp = spacy.load(model)
                    break
                except OSError:
                    continue
        except ImportError:
            self._nlp = None

    # ----- public API ------------------------------------------------------ #
    def is_blacklisted(self, name: str) -> bool:
        return _norm_key(name) in self._blacklist

    def resolve(self, name: str) -> CompanyInfo | None:
        """Resolve a raw name to a known company, or ``None``."""
        if self.is_blacklisted(name):
            return None
        return self._alias_index.get(_norm_key(name))

    def find_known_mentions(self, text: str) -> list[CompanyHit]:
        """Find all alias matches in ``text`` (non-overlapping, blacklist-aware)."""
        if not self._pattern or not text:
            return []
        hits: list[CompanyHit] = []
        for m in self._pattern.finditer(text):
            raw = m.group(0)
            if self.is_blacklisted(raw):
                continue
            info = self._alias_index.get(_norm_key(raw))
            if info is None:
                continue
            # Precision filters (avoid false positives) -----------------
            # 1) inside a URL / domain / handle -> not a statement about the co.
            if _looks_like_url(text, m.start(), m.end()):
                continue
            # 2) ambiguous common-word alias must appear capitalized
            #    ("intel" the noun vs. "Intel" the company).
            if info.ambiguous and raw == raw.lower():
                continue
            hits.append(CompanyHit(raw=raw, start=m.start(), end=m.end(), info=info))
        return hits

    def is_suppressed(self, info: CompanyInfo, text: str) -> bool:
        """Whole-post noise check (e.g. "Amazon" appearing only in a book promo).

        Keywords match on word boundaries, so "book" does not hit "facebook".
        """
        if not info.suppress_context:
            return False
        low = text.lower()
        return any(
            re.search(r"(?<![a-z0-9])" + re.escape(kw), low)
            for kw in info.suppress_context
        )

    def discover_org_candidates(self, text: str) -> list[str]:
        """spaCy-only: ORG entities not already covered by the alias table.

        Returns raw names (blacklist-filtered). Empty if spaCy is unavailable.
        """
        if self._nlp is None or not text:
            return []
        seen: set[str] = set()
        out: list[str] = []
        doc = self._nlp(text)
        for ent in doc.ents:
            if ent.label_ != "ORG":
                continue
            raw = ent.text.strip()
            key = _norm_key(raw)
            if not raw or key in seen:
                continue
            if self.is_blacklisted(raw) or key in self._alias_index:
                continue
            seen.add(key)
            out.append(raw)
        return out

    @property
    def has_spacy(self) -> bool:
        return self._nlp is not None

    def iter_companies(self) -> Iterator[CompanyInfo]:
        seen: set[str] = set()
        for info in self._alias_index.values():
            if info.normalized not in seen:
                seen.add(info.normalized)
                yield info
