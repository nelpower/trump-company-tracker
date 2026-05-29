"""Load the source list and obtain each source's text.

A source can provide its text three ways (checked in this order):
  1. inline ``text:`` in sources.yaml (best for short social posts)
  2. ``manual_text_file:`` -> read data/raw/manual_texts/<file>
  3. ``url:`` -> best-effort HTTP fetch (only if fetching is enabled)
If none yields text we also look for data/raw/manual_texts/<id>.txt.

Network fetching is intentionally optional so the pipeline runs fully offline.
"""
from __future__ import annotations

from pathlib import Path

from src.config import MANUAL_TEXTS_DIR, SOURCES_PATH, SOURCE_QUALITY, SOURCE_TYPES, load_yaml

USER_AGENT = (
    "Mozilla/5.0 (compatible; trump-company-tracker/0.1; research; "
    "+https://example.invalid/tracker)"
)
REQUIRED_FIELDS = ("id", "date", "source_type", "source_quality")


def load_sources(path=SOURCES_PATH) -> list[dict]:
    """Load and validate the source definitions."""
    data = load_yaml(path)
    sources = data.get("sources", []) if isinstance(data, dict) else []
    seen_ids: set[str] = set()
    valid: list[dict] = []
    for i, src in enumerate(sources):
        problems = [f for f in REQUIRED_FIELDS if not src.get(f)]
        if problems:
            print(f"[fetch] skip source #{i}: missing {problems}")
            continue
        if src["source_type"] not in SOURCE_TYPES:
            print(f"[fetch] warning: source {src['id']} has unknown "
                  f"source_type '{src['source_type']}'")
        if src["source_quality"] not in SOURCE_QUALITY:
            print(f"[fetch] warning: source {src['id']} has unknown "
                  f"source_quality '{src['source_quality']}'")
        if src["id"] in seen_ids:
            print(f"[fetch] skip duplicate source id '{src['id']}'")
            continue
        seen_ids.add(src["id"])
        valid.append(src)
    return valid


def _read_manual(filename: str) -> str | None:
    path = MANUAL_TEXTS_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    print(f"[fetch] manual_text_file not found: {path}")
    return None


def fetch_url(url: str, timeout: int = 20) -> str | None:
    """Best-effort fetch + readable-text extraction. Returns None on failure."""
    try:
        import requests
    except ImportError:
        print("[fetch] 'requests' not installed; cannot fetch URLs")
        return None
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - report and continue
        print(f"[fetch] failed to fetch {url}: {exc}")
        return None
    return _html_to_text(resp.text)


def _html_to_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
    except ImportError:
        import re

        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        import html as _html

        text = _html.unescape(text)
    import re

    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def get_source_text(source: dict, allow_fetch: bool = True) -> str | None:
    """Resolve a source to its text, trying inline -> file -> url -> <id>.txt."""
    if source.get("text"):
        return str(source["text"])
    if source.get("manual_text_file"):
        text = _read_manual(source["manual_text_file"])
        if text:
            return text
    if allow_fetch and source.get("url"):
        text = fetch_url(source["url"])
        if text:
            return text
    # last resort: a manual file named after the id
    fallback = Path(f"{source['id']}.txt")
    text = _read_manual(fallback.name)
    if text:
        return text
    print(f"[fetch] no text available for source '{source['id']}'")
    return None
