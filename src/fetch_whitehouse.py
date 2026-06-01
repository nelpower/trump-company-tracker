"""Ingest Trump's SPOKEN White House remarks as pipeline sources.

whitehouse.gov only posts videos (no transcripts), so spoken remarks were being
missed. The American Presidency Project (UCSB) maintains a clean, static,
authoritative archive of presidential *Spoken Addresses and Remarks* with full
transcripts — that is what we scrape here.

    listings: presidency.ucsb.edu/documents/app-categories/presidential/{
              spoken-addresses-and-remarks, news-conferences, interviews}
    doc page: .field-docs-content (transcript), .field-docs-person (speaker),
              .date-display-single (date)

Notes / honesty:
  * APP transcripts mark speakers ("The President." / "Q." / named reporters).
    We keep ONLY the "The President." segments so we never attribute a
    reporter's question to Trump.
  * APP is an archive: it lags the live event by days/weeks. Merge mode backfills
    remarks as they are added.
  * Incremental via data/processed/whitehouse_state.json (processed doc slugs).
  * Fully graceful: any network/parse failure yields no sources, never crashes.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from src.config import DEFAULT_SPEAKER, PROCESSED_DIR

BASE = "https://www.presidency.ucsb.edu"
LISTING_BASE = BASE + "/documents/app-categories/presidential/"
# All scanned via trump_only(), which keeps ONLY Trump's words in either the
# period format (remarks/pressers: "The President."/"Q.") or the colon format
# (interviews: "The President:"/"Sanger:"), and skips anything it can't attribute.
CATEGORY_SLUGS = [
    "spoken-addresses-and-remarks",   # speeches, gaggles, exchanges with reporters
    "news-conferences",               # formal press conferences
    "interviews",                     # TV / print interviews
]
STATE_PATH = PROCESSED_DIR / "whitehouse_state.json"
USER_AGENT = "Mozilla/5.0 (compatible; trump-company-tracker/0.3; research)"

# Speaker labels that introduce a segment in APP transcripts.
#  * remarks / news conferences use a PERIOD format:  "The President." / "Q."
#  * interviews use a COLON format:                    "The President:" / "Sanger:"
_SPEAKER_SPLIT = re.compile(r"(\bThe President\.|\bQ\.)")
_DATE_LEAD = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")
# A speaker label is a short proper-noun phrase before ": ", and only at a turn
# boundary (start of text or after sentence-ending . ? !) so a normal sentence
# word like "...Boeing." isn't swallowed into the next speaker's label.
_COLON_LABEL = re.compile(
    r"(?:(?<=[.?!])\s+|^)([A-Z][A-Za-z.'’\-]{1,20}(?:\s[A-Z][A-Za-z.'’\-]{1,20}){0,3}):\s")
_TRUMP_LABEL = re.compile(
    r"^(the president(?:-elect)?|president trump|donald(?: j\.?)? trump|mr\.? trump|trump)$",
    re.I)


def _get(url: str, timeout: int = 30) -> str | None:
    try:
        import requests
    except ImportError:
        print("[wh] 'requests' not installed; cannot fetch White House remarks")
        return None
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as exc:  # noqa: BLE001
        print(f"[wh] fetch failed {url}: {exc}")
        return None


def _parse_date(s: str) -> str:
    s = (s or "").strip()
    try:
        return dt.datetime.strptime(s, "%B %d, %Y").date().isoformat()
    except ValueError:
        return s


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def list_recent(max_items: int = 25) -> list[tuple[str, str, str]]:
    """Return [(doc_url, date_iso, title), ...] across all categories, or []."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("[wh] beautifulsoup4 not installed; cannot parse listing")
        return []
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for slug in CATEGORY_SLUGS:
        html = _get(f"{LISTING_BASE}{slug}?items_per_page={max_items}")
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for row in soup.select(".views-row"):
            a = row.find("a", href=True)
            if not a or "/documents/" not in a["href"]:
                continue
            url = a["href"] if a["href"].startswith("http") else BASE + a["href"]
            if url in seen:
                continue
            seen.add(url)
            text = re.sub(r"\s+", " ", row.get_text(" ", strip=True))
            m = _DATE_LEAD.match(text)
            date_iso = _parse_date(m.group(1)) if m else ""
            out.append((url, date_iso, a.get_text(" ", strip=True)))
    return out


def fetch_document(url: str) -> dict | None:
    """Fetch a doc page; return {content,date,title} only if it's a Trump remark."""
    html = _get(url)
    if not html:
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html, "html.parser")
    person = soup.select_one(".field-docs-person")
    if not person or "trump" not in person.get_text(" ", strip=True).lower():
        return None  # e.g. a foreign leader's address — skip
    content_el = soup.select_one(".field-docs-content")
    if not content_el:
        return None
    date_el = soup.select_one(".date-display-single")
    title_el = soup.select_one("h1")
    return {
        "content": content_el.get_text(" ", strip=True),
        "date": _parse_date(date_el.get_text(strip=True)) if date_el else "",
        "title": title_el.get_text(strip=True) if title_el else "",
    }


def trump_segments(content: str) -> str:
    """Keep only text spoken by 'The President.' (drop reporter Q&A)."""
    if not content:
        return ""
    parts = _SPEAKER_SPLIT.split(content)
    segs: list[str] = []
    i = 1
    while i < len(parts):
        label = parts[i].strip()
        text = parts[i + 1] if i + 1 < len(parts) else ""
        if label == "The President.":
            segs.append(text.strip())
        i += 2
    joined = re.sub(r"\s+", " ", " ".join(s for s in segs if s)).strip()
    return joined


def _colon_segments(content: str) -> tuple[list[str], set[str]]:
    """Split a colon-format transcript into Trump-only segments + all labels seen."""
    parts = _COLON_LABEL.split(content)
    segs: list[str] = []
    labels: set[str] = set()
    i = 1
    while i < len(parts):
        label = parts[i].strip()
        text = parts[i + 1] if i + 1 < len(parts) else ""
        labels.add(label)
        if _TRUMP_LABEL.match(label):
            segs.append(text.strip())
        i += 2
    return segs, labels


def trump_only(content: str) -> str:
    """Return ONLY Trump's words, across both transcript formats. Fail-safe:
    for a multi-speaker dialogue we never fall back to the full text (which would
    attribute reporters'/interviewers' words to Trump); we skip instead ("")."""
    if not content:
        return ""
    if "The President." in content:                 # period dialogue (remarks/presser)
        return trump_segments(content)
    segs, labels = _colon_segments(content)
    if len(labels) >= 2:                            # colon dialogue (interview)
        return re.sub(r"\s+", " ", " ".join(s for s in segs if s)).strip()
    return re.sub(r"\s+", " ", content).strip()     # monologue / formal speech (all Trump)


def get_sources(
    max_items: int = 25, max_new: int = 12, update_state: bool = True
) -> list[dict]:
    listing = list_recent(max_items)
    if not listing:
        return []
    state = load_state()
    processed: set[str] = set(state.get("processed", []))

    out: list[dict] = []
    seen: set[str] = set()
    for url, date_iso, title in listing:
        slug = url.rsplit("/documents/", 1)[-1]
        if slug in processed:
            continue
        doc = fetch_document(url)
        seen.add(slug)  # mark fetched (even non-Trump) so we don't refetch
        if not doc:
            continue
        text = trump_only(doc["content"])   # fail-safe: "" if not attributable
        if not text:
            continue
        out.append({
            "id": f"wh-{slug}",
            "date": doc["date"] or date_iso,
            "speaker": DEFAULT_SPEAKER,
            "title": doc["title"] or title,
            "url": url,
            "source_type": "white_house",
            "source_quality": "high",
            "verbatim_quote": True,
            "text": text,
        })
        if len(out) >= max_new:
            break

    print(f"[wh] {len(out)} new Trump remark(s) from American Presidency Project")
    if update_state and seen:
        processed.update(seen)
        save_state({"processed": sorted(processed),
                    "updated_at": dt.datetime.now(dt.timezone.utc)
                    .strftime("%Y-%m-%dT%H:%M:%SZ")})
    return out
