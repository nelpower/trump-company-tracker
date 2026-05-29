# Trump Company Mention Tracker

A reusable Python pipeline that **collects, normalizes, de-duplicates and
summarizes Donald Trump's public statements that mention *specific* companies**
(public or private), for **investment research**.

> This is a **fact-collection / signal-tracking** tool. It is **not** political
> opinion analysis, advocacy, or mobilization. It only records *what was said,
> about which company, where, and what the possible policy/investment angle is*.
> **Trump's statements are attention/policy signals, not buy/sell
> recommendations** — always verify against filings, orders, cash flow,
> valuation and industry logic.

---

## What it does

For every statement that names a concrete company/brand/ticker, it extracts a
structured record with 24 fields (exact quote, source, normalized company name,
ticker, sector, themes, sentiment, policy angle, an investment-relevance score,
bilingual summaries, a confidence score, and provenance notes) and writes:

- `outputs/trump_company_mentions.csv` (Excel-friendly, UTF-8 BOM)
- `outputs/trump_company_mentions.jsonl` (one JSON object per line)
- `outputs/report.md` (a human-readable research report)

It **only keeps statements that name a specific company.** Generic industry
talk ("semiconductors", "automakers", "AI companies") with no named company is
dropped, and noise like *America*, *the White House*, *Truth* is blacklisted.

### Pipeline stages (`src/`)

| Stage | Module | Responsibility |
|---|---|---|
| 1 | `fetch_sources.py` | Load `sources.yaml`; get each source's text (inline / manual file / URL) |
| 1b | `fetch_truth_social.py` | Pull Trump's Truth Social feed (incremental) as sources |
| 2 | `extract_mentions.py` | Split into sentences; emit one record per (source, company) |
| 3 | `normalize_companies.py` | Alias dictionary (+ optional spaCy NER) → canonical name; blacklist + precision filters |
| 4 | `enrich_tickers.py` | Fill ticker/exchange (alias table → optional SEC file → optional yfinance); never invents |
| 5 | `score_relevance.py` | Themes, policy angle, sentiment, relevance (1-5), confidence (1-5), summaries |
| 6 | `dedupe.py` | Merge the same statement across sources; keep the highest-quality one |
| 7 | `generate_report.py` / `build_site.py` | Build `report.md` and the static website |
| — | `pipeline.py` | Orchestrates 1→7 (merge/accumulate mode) |

**Precision filters** (in `normalize_companies.py`, to fight false positives the
automated feed produces): ambiguous common-word aliases must be capitalized
(`intel`≠Intel), matches inside URLs are dropped (`amazon.com/dp/…`), per-company
noise context is suppressed (book-promo "Amazon" links), and a sentence naming
≥4 companies is treated as a name-drop list (relevance capped, themes unreliable).

---

## Install

Requires Python 3.9+. The **core** pipeline only needs `PyYAML`.

```bash
cd trump-company-tracker
python -m pip install -r requirements.txt        # core + fetch + pytest
# or, editable with extras:
python -m pip install -e ".[fetch,dev]"
```

Optional extras:

```bash
# Discover companies NOT yet in the alias table (NER):
python -m pip install spacy && python -m spacy download en_core_web_sm
# Validate tickers online:
python -m pip install yfinance
# Notebook:
python -m pip install pandas jupyter
```

---

## Run

From the project root:

```bash
python -m src.pipeline                 # use data/sources.yaml, fetch if needed
python -m src.pipeline --no-fetch      # fully offline (inline + manual text only)
python -m src.pipeline --use-spacy     # also surface unknown ORGs for review
python -m src.pipeline --min-confidence 4   # keep only high-confidence records

# Truth Social daily feed (auto-collects Trump's own posts) + build the site:
python -m src.pipeline --truth-social --site-dir site
python -m src.pipeline --truth-social --truth-since 2025-12-01 --no-merge  # backfill
```

The run is **idempotent and accumulating**: record ids are a stable hash of
`date + company + quote`. In the default *merge* mode the output JSONL is a
growing dataset — each run loads it, adds newly-found mentions, de-dupes, and
writes it back. Truth Social ingestion is incremental (a small state file
tracks the last processed post). Use `--no-merge` for a clean rebuild.

Run the tests:

```bash
python -m pytest            # 69 tests
```

---

## Daily web page (GitHub Pages)

The repo ships a daily-updating website: a GitHub Actions workflow
(`.github/workflows/daily.yml`) runs every day at **04:00 UTC = 12:00 Beijing**,
pulls Trump's Truth Social feed, runs the pipeline, builds a mobile-friendly
static site, and deploys it to GitHub Pages. The browsable page shows **今日/最近
提及**, **高投资相关性 (≥4)**, **近 30 天**, and an **按公司** table — each as a card
with the quote, sentiment, policy angle, relevance stars and a source link.

**Data source.** Trump has no official Truth Social API, so we consume a free,
auto-updating public mirror of his timeline (`fetch_truth_social.py`). These are
his own posts → verbatim, consistent with the "direct quotes only" rule. Only
posts that name a company in `company_aliases.yaml` survive; most days that is
zero (and the page says so).

**One-time setup**

```bash
cd trump-company-tracker
git init && git add -A && git commit -m "init"
gh repo create trump-company-tracker --public --source=. --push
# or: create a repo on github.com and `git remote add origin … && git push -u origin main`
```

Then in the repo: **Settings → Pages → Build and deployment → Source =
GitHub Actions**. Trigger the first run from the **Actions** tab
("daily-update" → *Run workflow*). The site appears at
`https://<user>.github.io/<repo>/`.

- The workflow commits the refreshed `outputs/` + state back to the repo, so the
  dataset **accumulates** day over day.
- The ~18 MB feed cache is git-ignored; only small derived files are committed.
- Want it private? GitHub Pages is public on the free plan — use **Cloudflare
  Pages** (build command `pip install -r requirements.txt && python -m
  src.pipeline --truth-social --site-dir site`, output dir `site`) with Access,
  or keep it local (Windows Task Scheduler + `--site-dir`).

To change the schedule, edit the `cron:` line (it is in UTC).

---

## Adding a new source

Edit `data/sources.yaml`. Required: `id`, `date` (of the *statement*),
`source_type`, `source_quality`. Provide the text one of three ways:

```yaml
sources:
  # (a) inline text — best for short social posts
  - id: my-source-1
    date: 2025-05-01
    title: "Some remarks"
    url: "https://example.com/article"     # always keep for provenance
    source_type: social_media              # white_house | social_media |
                                           # video_transcript | news |
                                           # company_release | other
    source_quality: high                   # official | high | medium | low
    verbatim_quote: true                   # it's a direct quote (raises conf.)
    text: >-
      Trump's exact words mentioning Acme Corp go here.

  # (b) a transcript file under data/raw/manual_texts/
  - id: my-source-2
    date: 2025-05-02
    source_type: white_house
    source_quality: official
    manual_text_file: my_transcript.txt

  # (c) just a URL (fetched if fetching is enabled; falls back to manual text)
  - id: my-source-3
    date: 2025-05-03
    source_type: news
    source_quality: medium
    url: "https://example.com/story"
```

If a page can't be fetched, paste the transcript into
`data/raw/manual_texts/<id>.txt` (or any name referenced by `manual_text_file`)
and re-run.

### Maintaining company knowledge

- **Add/curate companies** → `data/company_aliases.yaml` (name, aliases,
  ticker, exchange, status, sector, default themes). HP Inc. (`HPQ`) and
  Hewlett Packard Enterprise (`HPE`) are kept distinct, for example.
- **Stop a false positive** → add the term to `data/blacklist.yaml`.
- **Override a heuristic** (e.g. a curated sentiment) → add `overrides` to a
  source keyed by the normalized company name (or `_all_`).

### Optional: better ticker coverage

Download the SEC ticker map once (kept out of git):

```bash
curl -o data/raw/sec_company_tickers.json https://www.sec.gov/files/company_tickers.json
```

The pipeline will then resolve tickers for companies not in the alias table.

---

## Field reference (output schema)

`id, date, speaker, source_title, source_url, source_type, source_quality,
exact_quote, quote_context_before, quote_context_after, mentioned_company_raw,
normalized_company_name, ticker_if_public, exchange_if_public, company_status,
sector, theme_tags, sentiment_toward_company, policy_angle,
investment_relevance_score, summary_zh, summary_en, confidence_score, notes`

**Investment-relevance rubric** (`investment_relevance_score`):

| Score | Meaning |
|---|---|
| 5 | Named company **and** a critical sector or concrete policy lever (gov contract, defense, AI infra, data center, US manufacturing, tariff/subsidy, energy, semiconductor, telecom) |
| 4 | Named company with positive/negative context that may move perception, but no direct order/policy |
| 3 | Company mentioned, investment implication unclear |
| 2 | Brand/company mentioned only in passing |
| 1 | Almost no investment value; historical record only |

**Confidence** caps: a `news` paraphrase without `verbatim_quote`, an explicit
`quote_uncertain`, or a non-Trump speaker all cap `confidence_score` at 3.

---

## Data quality rules (enforced by design)

- Every record has a `source_url` **and** an `exact_quote`.
- Only **direct quotes** are ingested — news *summaries/analysis* are not
  treated as Trump's words.
- Tickers are **never fabricated**; unknown → blank + `company_status: unknown`.
- De-dup keeps the **highest-quality** source (official > high > medium > low)
  and records the others in `notes`.

---

## Limitations

- **Sentence-level quote extraction.** The `exact_quote` is the sentence(s)
  containing the company name. A long, rambling statement may need manual
  trimming. The splitter protects common abbreviations but is not a full NLP
  model.
- **Heuristic classification.** Sentiment / theme / policy / relevance come
  from transparent keyword rules, not a model. They are a consistent first pass
  meant to be reviewed/overridden, not ground truth.
- **Automated feed precision.** The Truth Social feed yields false positives the
  filters only partly catch: a CEO's surname can read as the company (e.g.
  "Michael Dell" the person vs. Dell Technologies), name-drop lists mix many
  companies in one sentence (themes get cross-contaminated; we cap their
  relevance), and re-truths can surface someone else's words. Spot-check
  `exact_quote` for anything you act on.
- **Third-party data dependency.** The Truth Social mirror is community-hosted
  (no official API, no license guarantee); if it moves or stops, ingestion needs
  a new source (trumpstruth.org / White House remarks are documented fallbacks).
- **GitHub Pages is public** on the free plan — use Cloudflare Pages + Access or
  a local build if the page must stay private.
- **Recall depends on the alias table.** A company not in
  `company_aliases.yaml` is missed unless you enable spaCy NER (which only
  *flags* unknown ORGs for review — it never assigns a ticker).
- **Short/ambiguous aliases** (e.g. `Ford`, `GM`) can false-positive on names;
  the blacklist and word-boundary matching mitigate but don't eliminate this.
- **Provenance for social posts.** Trump's own accounts aren't directly
  fetchable, so social-media `source_url`s point to reputable outlets that
  reproduce the verbatim quote (noted per record).
- **No live market data.** This tool tracks *statements*, not prices.

## Possible extensions

- Real transcript ingestion from the White House / C-SPAN feeds and Roll Call.
- Quote-attribution NLP to pull Trump's verbatim words out of news articles
  automatically (instead of manual curation).
- Entity linking to permanent identifiers (CIK, LEI, ISIN) and corporate-tree
  resolution (subsidiary → parent).
- Event-study hooks: join each mention to next-session price/volume reaction.
- Push/email alerting on new high-relevance mentions (the daily site already
  ships; alerting + an interactive filter UI are natural next steps).
- Person-vs-company disambiguation and better re-truth detection.
- Multilingual sources and translation of non-English remarks.

---

## Project layout

```
trump-company-tracker/
  README.md                requirements.txt   pyproject.toml
  .github/workflows/daily.yml        (daily build + GitHub Pages deploy)
  data/
    sources.yaml           company_aliases.yaml   blacklist.yaml
    raw/manual_texts/      processed/ (truth_state.json)
  src/
    fetch_sources.py  fetch_truth_social.py  extract_mentions.py
    normalize_companies.py  enrich_tickers.py  dedupe.py
    score_relevance.py  generate_report.py  build_site.py
    pipeline.py  config.py  models.py
  tests/        notebooks/exploration.ipynb
  outputs/      (generated CSV / JSONL / report.md)
  site/         (generated static website; deployed by CI)
```
