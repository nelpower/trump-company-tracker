"""Tests for the translation cache (no network: the translator is stubbed)."""
from src import translate
from src.models import Mention


def test_cache_hit_avoids_network(monkeypatch):
    calls = []
    monkeypatch.setattr(translate, "_translate_one",
                        lambda t: calls.append(t) or "SHOULD_NOT_USE")
    cache = {translate._key("hello"): "你好"}
    assert translate.translate_to_zh("hello", cache) == "你好"
    assert calls == []  # served from cache, translator not called


def test_translates_and_caches(monkeypatch):
    monkeypatch.setattr(translate, "_translate_one", lambda t: "译:" + t)
    cache = {}
    assert translate.translate_to_zh("hi", cache) == "译:hi"
    assert translate._key("hi") in cache  # now cached


def test_graceful_on_failure_not_cached(monkeypatch):
    monkeypatch.setattr(translate, "_translate_one", lambda t: None)
    cache = {}
    assert translate.translate_to_zh("x", cache) == ""
    assert translate._key("x") not in cache  # so a later run can retry


def test_empty_text_no_call(monkeypatch):
    monkeypatch.setattr(translate, "_translate_one",
                        lambda t: (_ for _ in ()).throw(AssertionError("called")))
    assert translate.translate_to_zh("", {}) == ""


def test_translate_mentions(monkeypatch, tmp_path):
    monkeypatch.setattr(translate, "_translate_one", lambda t: "ZH:" + t)
    ms = [Mention(exact_quote="Buy a Dell."), Mention(exact_quote="")]
    n = translate.translate_mentions(ms, path=tmp_path / "tr.json")
    assert ms[0].exact_quote_zh == "ZH:Buy a Dell."
    assert ms[1].exact_quote_zh == ""   # empty quote stays empty
    assert n == 1                        # one new translation
