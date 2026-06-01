"""End-to-end pipeline: sources -> mentions -> normalize -> enrich -> dedupe ->
CSV / JSONL / report / static site.

Run from the project root:
    python -m src.pipeline                       # curated sources.yaml only
    python -m src.pipeline --truth-social        # + daily Truth Social feed
    python -m src.pipeline --truth-social --site-dir site   # also build the site
    python -m src.pipeline --no-fetch            # never hit the network
    python -m src.pipeline --no-merge            # clean rebuild (ignore prior output)

Idempotency / accumulation:
  * Record ids are a stable hash of (date + company + quote).
  * In merge mode (default) the output JSONL is a *growing* dataset: each run
    loads it, adds newly-found mentions, de-dupes by id, and writes it back.
    Re-running changes nothing if there are no new posts.
  * Truth Social ingestion is incremental (see fetch_truth_social state file).
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src import config, fetch_truth_social, fetch_whitehouse
from src.build_site import build_site
from src.dedupe import dedupe
from src.enrich_tickers import enrich, load_sec_index
from src.extract_mentions import extract_from_source
from src.fetch_sources import get_source_text, load_sources
from src.generate_report import write_report
from src.models import Mention
from src.normalize_companies import CompanyResolver
from src.score_relevance import enrich_scoring
from src.translate import translate_mentions
from src.trades import load_trades


def write_csv(mentions: list[Mention], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=config.FIELDNAMES)
        writer.writeheader()
        for m in mentions:
            writer.writerow(m.to_csv_row())


def write_jsonl(mentions: list[Mention], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for m in mentions:
            fh.write(json.dumps(m.to_json_obj(), ensure_ascii=False) + "\n")


def load_existing(path: Path) -> list[Mention]:
    """Load a previously written JSONL dataset (for merge mode)."""
    if not path.exists():
        return []
    out: list[Mention] = []
    for line in path.open("r", encoding="utf-8"):
        line = line.strip()
        if line:
            out.append(Mention.from_dict(json.loads(line)))
    return out


def _process_sources(sources, resolver, sec_index) -> list[Mention]:
    found: list[Mention] = []
    for src in sources:
        text = get_source_text(src, allow_fetch=src.get("_allow_fetch", True))
        if not text:
            continue
        src = {**src, "text": text}
        mentions = extract_from_source(src, resolver)
        for m in mentions:
            enrich(m, sec_index)
            enrich_scoring(m, src)
        found.extend(mentions)
    return found


def run(
    sources_path: Path = config.SOURCES_PATH,
    aliases_path: Path = config.ALIASES_PATH,
    blacklist_path: Path = config.BLACKLIST_PATH,
    outputs_dir: Path | None = None,
    allow_fetch: bool = True,
    use_spacy: bool = False,
    min_confidence: int = 1,
    truth_social: bool = False,
    truth_since: str | None = None,
    truth_lookback_days: int = 60,
    truth_max: int | None = None,
    whitehouse: bool = False,
    whitehouse_max: int = 12,
    merge: bool = True,
    site_dir: Path | None = None,
) -> list[Mention]:
    outputs_dir = outputs_dir or config.OUTPUTS_DIR
    jsonl_out = outputs_dir / config.JSONL_OUT.name

    resolver = CompanyResolver(aliases_path, blacklist_path, use_spacy=use_spacy)
    if use_spacy and not resolver.has_spacy:
        print("[pipeline] --use-spacy requested but spaCy/model unavailable; "
              "continuing with dictionary matching only.")
    sec_index = load_sec_index()

    # 1) curated sources
    sources = load_sources(sources_path)
    for s in sources:
        s["_allow_fetch"] = allow_fetch
    print(f"[pipeline] loaded {len(sources)} curated source(s)")

    # 2) Truth Social feed (incremental)
    if truth_social:
        ts_sources = fetch_truth_social.get_sources(
            since_iso=truth_since,
            lookback_days=truth_lookback_days,
            max_posts=truth_max,
        )
        for s in ts_sources:
            s["_allow_fetch"] = allow_fetch
        sources.extend(ts_sources)

    # 2b) White House spoken remarks (American Presidency Project)
    if whitehouse:
        wh_sources = fetch_whitehouse.get_sources(max_new=whitehouse_max)
        for s in wh_sources:
            s["_allow_fetch"] = allow_fetch
        sources.extend(wh_sources)

    new_mentions = _process_sources(sources, resolver, sec_index)
    print(f"[pipeline] extracted {len(new_mentions)} company mention(s) this run")

    # 3) merge with the accumulated dataset (preserves history + manual edits)
    existing = load_existing(jsonl_out) if merge else []
    if existing:
        print(f"[pipeline] merging with {len(existing)} existing record(s)")
    deduped = dedupe(existing + new_mentions)

    if min_confidence > 1:
        before = len(deduped)
        deduped = [m for m in deduped if m.confidence_score >= min_confidence]
        print(f"[pipeline] confidence filter (>= {min_confidence}): "
              f"{before} -> {len(deduped)}")

    # 3b) Chinese translation of each quote (cached; only new quotes hit network)
    n_translated = translate_mentions(deduped)
    if n_translated:
        print(f"[pipeline] translated {n_translated} new quote(s) to Chinese")

    # 4) write outputs
    csv_out = outputs_dir / config.CSV_OUT.name
    report_out = outputs_dir / config.REPORT_OUT.name
    write_csv(deduped, csv_out)
    write_jsonl(deduped, jsonl_out)
    write_report(deduped, report_out)
    outs = [csv_out, jsonl_out, report_out]

    if site_dir is not None:
        trades = load_trades()
        index = build_site(deduped, Path(site_dir), trades=trades)
        outs.append(index)
        print(f"[pipeline] overlaid {len(trades)} curated Trump trade(s)")

    print(f"[pipeline] dataset now {len(deduped)} record(s)")
    print("[pipeline] wrote:\n  " + "\n  ".join(str(p) for p in outs))
    return deduped


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Trump company mention tracker pipeline")
    p.add_argument("--sources", type=Path, default=config.SOURCES_PATH)
    p.add_argument("--aliases", type=Path, default=config.ALIASES_PATH)
    p.add_argument("--blacklist", type=Path, default=config.BLACKLIST_PATH)
    p.add_argument("--outputs-dir", type=Path, default=config.OUTPUTS_DIR)
    p.add_argument("--no-fetch", action="store_true",
                   help="never hit the network; use only inline/manual text")
    p.add_argument("--use-spacy", action="store_true",
                   help="also surface unknown ORG entities (requires spaCy)")
    p.add_argument("--min-confidence", type=int, default=1,
                   help="drop records below this confidence_score (1-5)")
    # Truth Social
    p.add_argument("--truth-social", action="store_true",
                   help="ingest Trump's Truth Social feed (incremental)")
    p.add_argument("--truth-since", default=None,
                   help="process posts on/after this date (YYYY-MM-DD)")
    p.add_argument("--truth-lookback-days", type=int, default=60,
                   help="first-run backfill window when there is no saved state")
    p.add_argument("--truth-max", type=int, default=None,
                   help="cap number of posts processed (safety)")
    # White House
    p.add_argument("--whitehouse", action="store_true",
                   help="ingest Trump's spoken White House remarks (APP archive)")
    p.add_argument("--whitehouse-max", type=int, default=12,
                   help="max new White House remarks to fetch per run")
    p.add_argument("--no-merge", action="store_true",
                   help="clean rebuild: ignore the previously written dataset")
    # Site
    p.add_argument("--site-dir", type=Path, default=None,
                   help="build the static site into this directory")
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    run(
        sources_path=args.sources,
        aliases_path=args.aliases,
        blacklist_path=args.blacklist,
        outputs_dir=args.outputs_dir,
        allow_fetch=not args.no_fetch,
        use_spacy=args.use_spacy,
        min_confidence=args.min_confidence,
        truth_social=args.truth_social,
        truth_since=args.truth_since,
        truth_lookback_days=args.truth_lookback_days,
        truth_max=args.truth_max,
        whitehouse=args.whitehouse,
        whitehouse_max=args.whitehouse_max,
        merge=not args.no_merge,
        site_dir=args.site_dir,
    )


if __name__ == "__main__":
    main()
