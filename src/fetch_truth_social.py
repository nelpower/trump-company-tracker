"""Ingest Trump's Truth Social posts as pipeline sources.

Data source: a free, auto-updating public mirror of Trump's Truth Social
timeline (JSON, refreshed every few minutes). These are posts from his own
account, i.e. *verbatim* — consistent with the project's "direct quotes only,
never fabricate" rule.

    primary : https://ix.cnn.io/data/truth-social/truth_archive.json
    fallback: https://stilesdata.com/trump-truth-social-archive/truth_archive.json

Each post: {id, created_at, content(html), url, media, *_count}.

Design notes:
  * Incremental — state (last processed timestamp) lives in
    data/processed/truth_state.json so daily runs only handle new posts.
  * The downloaded feed is cached on the D: drive and git-ignored (it's ~18 MB);
    only the small derived outputs/state are committed.
  * Re-truths (reposts of others) cannot be reliably distinguished from the feed
    fields, so a mention is tagged in notes when uncertain. Confidence still
    derives from source_quality.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path

from src.config import DEFAULT_SPEAKER, PROCESSED_DIR, RAW_DIR

FEED_URLS = [
    "https://ix.cnn.io/data/truth-social/truth_archive.json",
    "https://stilesdata.com/trump-truth-social-archive/truth_archive.json",
]
CACHE_PATH = RAW_DIR / "truth_archive.json"
STATE_PATH = PROCESSED_DIR / "truth_state.json"

USER_AGENT = (
    "Mozilla/5.0 (compatible; trump-company-tracker/0.2; research)"
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(content: str) -> str:
    """Turn a post's HTML body into clean plain text."""
    if not content:
        return ""
    text = content.replace("</p>", "\n").replace("<br>", "\n").replace("<br/>", "\n")
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    # keep paragraph breaks but collapse runs of spaces
    lines = [_WS_RE.sub(" ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


# --------------------------------------------------------------------------- #
# Feed download (with on-disk cache)
# --------------------------------------------------------------------------- #
def download_feed(
    force: bool = False, max_age_minutes: int = 180, timeout: int = 60
) -> list[dict]:
    """Return the feed as a list of post dicts, using a fresh-enough cache."""
    if not force and CACHE_PATH.exists():
        age_min = (
            dt.datetime.now().timestamp() - CACHE_PATH.stat().st_mtime
        ) / 60
        if age_min <= max_age_minutes:
            try:
                return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass  # fall through and re-download

    try:
        import requests
    except ImportError:
        print("[truth] 'requests' not installed; cannot download feed. "
              "Install with: pip install requests")
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return []

    for url in FEED_URLS:
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT},
                                timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(json.dumps(data), encoding="utf-8")
            print(f"[truth] downloaded {len(data)} posts from {url}")
            return data
        except Exception as exc:  # noqa: BLE001
            print(f"[truth] feed failed ({url}): {exc}")
    if CACHE_PATH.exists():
        print("[truth] using stale cache after download failure")
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return []


# --------------------------------------------------------------------------- #
# State (incremental processing)
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Post -> source dict
# --------------------------------------------------------------------------- #
def post_to_source(post: dict) -> dict | None:
    """Convert one Truth Social post into a pipeline 'source'. None if empty."""
    text = strip_html(post.get("content", "") or "")
    if not text:
        return None  # link/image-only post, nothing to quote
    pid = str(post.get("id", "")).strip()
    created = post.get("created_at", "") or ""
    date = created[:10]
    url = post.get("url") or (f"https://trumpstruth.org/statuses/{pid}" if pid else "")
    return {
        "id": f"ts-{pid}" if pid else f"ts-{date}",
        "date": date,
        "speaker": DEFAULT_SPEAKER,
        "title": f"Truth Social post ({date})",
        "url": url,
        "source_type": "social_media",
        "source_quality": "high",
        "verbatim_quote": True,
        "text": text,
        "_created_at": created,  # internal, for state tracking
    }


def _shift_iso(iso: str, days: int) -> str:
    """Shift an ISO timestamp/date back by N days (overlap safety)."""
    base = iso[:10]
    try:
        d = dt.date.fromisoformat(base) - dt.timedelta(days=days)
        return d.isoformat()
    except ValueError:
        return base


def get_sources(
    since_iso: str | None = None,
    lookback_days: int = 60,
    max_posts: int | None = None,
    update_state: bool = True,
    overlap_days: int = 1,
) -> list[dict]:
    """Return source dicts for posts at/after a cutoff.

    Cutoff precedence: explicit ``since_iso`` -> state's last timestamp (minus
    ``overlap_days``) -> now minus ``lookback_days`` (first run / backfill).
    """
    posts = download_feed()
    if not posts:
        return []

    if since_iso is None:
        state = load_state()
        last = state.get("last_created_at")
        if last:
            since_iso = _shift_iso(last, overlap_days)
        else:
            since_iso = (dt.date.today() - dt.timedelta(days=lookback_days)).isoformat()

    # ISO-8601 strings sort lexicographically, so a string compare is correct.
    recent = [p for p in posts if (p.get("created_at") or "") >= since_iso]
    recent.sort(key=lambda p: p.get("created_at") or "")

    sources: list[dict] = []
    max_seen = since_iso
    for post in recent:
        max_seen = max(max_seen, post.get("created_at") or "")
        src = post_to_source(post)
        if src:
            sources.append(src)
    # Cap to the most-recent N *usable* posts (after dropping empty ones).
    if max_posts and len(sources) > max_posts:
        sources = sources[-max_posts:]

    print(f"[truth] {len(sources)} post(s) with text since {since_iso} "
          f"(of {len(recent)} new)")

    if update_state and recent:
        save_state({"last_created_at": max_seen,
                    "updated_at": dt.datetime.now(dt.timezone.utc)
                    .strftime("%Y-%m-%dT%H:%M:%SZ")})
    return sources
