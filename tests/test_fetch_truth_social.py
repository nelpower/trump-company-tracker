"""Tests for Truth Social ingestion (no network: the feed is monkeypatched)."""
from src import fetch_truth_social as ts


SAMPLE_POSTS = [
    {"id": "111", "created_at": "2026-05-20T10:00:00.000Z",
     "content": "<p>I think <b>Intel</b> is doing great things in Arizona!</p>",
     "url": "https://truthsocial.com/@realDonaldTrump/111"},
    {"id": "112", "created_at": "2026-05-28T12:00:00.000Z",
     "content": "<p>Just a generic political post, no companies here.</p>",
     "url": "https://truthsocial.com/@realDonaldTrump/112"},
    {"id": "113", "created_at": "2026-04-01T08:00:00.000Z",
     "content": "<p>An old post about Boeing &amp; jobs.</p>",
     "url": "https://truthsocial.com/@realDonaldTrump/113"},
    {"id": "114", "created_at": "2026-05-29T09:00:00.000Z",
     "content": "", "url": "https://truthsocial.com/@realDonaldTrump/114"},
]


def test_strip_html():
    assert ts.strip_html("<p>Hello <a href='x'>world</a></p>") == "Hello world"
    assert ts.strip_html("A &amp; B &lt;3") == "A & B <3"
    assert ts.strip_html("") == ""


def test_post_to_source_fields():
    src = ts.post_to_source(SAMPLE_POSTS[0])
    assert src is not None
    assert src["id"] == "ts-111"
    assert src["date"] == "2026-05-20"
    assert src["source_type"] == "social_media"
    assert src["source_quality"] == "high"
    assert src["verbatim_quote"] is True
    assert "Intel" in src["text"]
    assert src["url"].endswith("/111")


def test_post_to_source_skips_empty():
    assert ts.post_to_source(SAMPLE_POSTS[3]) is None


def test_get_sources_since_filter(monkeypatch):
    monkeypatch.setattr(ts, "download_feed", lambda *a, **k: list(SAMPLE_POSTS))
    sources = ts.get_sources(since_iso="2026-05-01", update_state=False)
    ids = {s["id"] for s in sources}
    # 111 (May 20) and 112 (May 28) are after the cutoff and have text;
    # 113 (Apr 1) is before; 114 is empty -> dropped.
    assert ids == {"ts-111", "ts-112"}


def test_get_sources_max_posts_keeps_most_recent(monkeypatch):
    monkeypatch.setattr(ts, "download_feed", lambda *a, **k: list(SAMPLE_POSTS))
    sources = ts.get_sources(since_iso="2026-01-01", max_posts=1,
                             update_state=False)
    assert len(sources) == 1
    assert sources[0]["id"] == "ts-112"  # most recent non-empty (May 28)
