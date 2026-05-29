"""Chinese translation of quotes, with an on-disk cache.

Uses ``deep-translator`` (Google backend, no API key). Every quote is translated
at most once: results are cached in ``data/processed/translations.json`` (keyed
by a hash of the source text) and committed back by CI, so daily runs only
translate genuinely new quotes and never re-hit the network for old ones.

Fully graceful: if the package is missing or the network fails, the Chinese
field is simply left empty and the pipeline continues.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.config import PROCESSED_DIR

CACHE_PATH = PROCESSED_DIR / "translations.json"
_MAX_LEN = 4800  # Google free endpoint per-request limit is ~5000 chars


def _key(text: str) -> str:
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:16]


def load_cache(path: Path = CACHE_PATH) -> dict[str, str]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_cache(cache: dict[str, str], path: Path = CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # stable ordering keeps the committed file diff-friendly
    path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True),
        encoding="utf-8",
    )


def _translate_one(text: str) -> str | None:
    """Translate to Simplified Chinese, or None on any failure."""
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        return None
    try:
        zh = GoogleTranslator(source="auto", target="zh-CN").translate(text[:_MAX_LEN])
        return zh or None
    except Exception:  # noqa: BLE001 - never let translation break the pipeline
        return None


def translate_to_zh(text: str, cache: dict[str, str]) -> str:
    """Return the Chinese translation of ``text`` (cached). Empty on failure."""
    text = (text or "").strip()
    if not text:
        return ""
    k = _key(text)
    if k in cache:
        return cache[k]
    zh = _translate_one(text)
    if zh:
        cache[k] = zh
        return zh
    return ""  # not cached, so a later run can retry


def translate_mentions(mentions, path: Path = CACHE_PATH) -> int:
    """Fill ``exact_quote_zh`` for every mention. Returns # newly translated."""
    cache = load_cache(path)
    before = len(cache)
    for m in mentions:
        if not getattr(m, "exact_quote_zh", ""):
            m.exact_quote_zh = translate_to_zh(m.exact_quote, cache)
    if len(cache) != before:
        save_cache(cache, path)
    return len(cache) - before
