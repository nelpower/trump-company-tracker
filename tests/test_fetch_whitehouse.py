"""Tests for White House (American Presidency Project) ingestion.

No network: HTTP responses are monkeypatched.
"""
from src import fetch_whitehouse as wh


def test_trump_segments_keeps_only_president():
    content = ("The President. We love Boeing. Q. What about Intel? "
               "The President. Intel is doing great.")
    out = wh.trump_segments(content)
    assert "We love Boeing." in out
    assert "Intel is doing great." in out
    assert "What about Intel?" not in out  # reporter question dropped


def test_trump_segments_empty():
    assert wh.trump_segments("") == ""


def test_parse_date():
    assert wh._parse_date("April 13, 2026") == "2026-04-13"
    assert wh._parse_date("May 8, 2026") == "2026-05-08"


def test_fetch_document_filters_non_trump(monkeypatch):
    trump_html = ('<h1>Remarks</h1>'
                  '<div class="field-docs-person">Donald J. Trump (2nd Term)</div>'
                  '<span class="date-display-single">April 13, 2026</span>'
                  '<div class="field-docs-content">The President. Go buy a Dell.</div>')
    other_html = ('<h1>Address</h1>'
                  '<div class="field-docs-person">Charles III</div>'
                  '<div class="field-docs-content">Hello Congress.</div>')
    monkeypatch.setattr(wh, "_get", lambda url, timeout=30: trump_html)
    doc = wh.fetch_document("http://x")
    assert doc and doc["date"] == "2026-04-13" and "Dell" in doc["content"]

    monkeypatch.setattr(wh, "_get", lambda url, timeout=30: other_html)
    assert wh.fetch_document("http://y") is None  # not Trump -> skipped


def test_list_recent(monkeypatch):
    listing = ('<div class="views-row">'
               '<a href="/documents/remarks-foo">April 13, 2026 Remarks Foo</a>'
               ' Related Donald J. Trump (2nd Term)</div>')
    monkeypatch.setattr(wh, "_get", lambda url, timeout=30: listing)
    rows = wh.list_recent()
    assert len(rows) == 1
    assert rows[0][0].endswith("/documents/remarks-foo")
    assert rows[0][1] == "2026-04-13"


def test_get_sources_skips_processed(monkeypatch, tmp_path):
    listing = ('<div class="views-row">'
               '<a href="/documents/remarks-foo">April 13, 2026 Foo</a>'
               ' Donald J. Trump (2nd Term)</div>')
    doc = ('<h1>Foo</h1>'
           '<div class="field-docs-person">Donald J. Trump (2nd Term)</div>'
           '<span class="date-display-single">April 13, 2026</span>'
           '<div class="field-docs-content">The President. Buy a Dell.</div>')

    def fake_get(url, timeout=30):
        return listing if url.startswith(wh.LISTING) else doc

    monkeypatch.setattr(wh, "_get", fake_get)
    monkeypatch.setattr(wh, "STATE_PATH", tmp_path / "wh_state.json")
    first = wh.get_sources()
    assert len(first) == 1 and first[0]["source_type"] == "white_house"
    # second run: already processed -> nothing new
    second = wh.get_sources()
    assert second == []
