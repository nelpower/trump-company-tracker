"""Render a self-contained, mobile-friendly static site from the mentions.

Produces ``<site_dir>/index.html`` (inline CSS, no JS/CDN dependencies) plus a
downloadable ``<site_dir>/data.jsonl``. Designed to be published by GitHub Pages.
"""
from __future__ import annotations

import datetime as dt
import html
import json
from collections import Counter, defaultdict
from pathlib import Path

from src.config import BASE_DIR
from src.models import Mention
from src.score_relevance import _POLICY_ZH, _SENTI_ZH

SITE_DIR = BASE_DIR / "site"

DISCLAIMER = (
    "本站仅收集整理特朗普公开言论中对具体公司的提及，作为投资研究的"
    "「注意力 / 政策线索」追踪。言论不构成任何买卖建议，必须结合财报、订单、"
    "现金流、估值与产业逻辑独立验证。分类由启发式规则自动生成，可能有误，"
    "请以 exact_quote 与来源链接为准。"
)

_SENTI_CLASS = {"positive": "pos", "negative": "neg", "neutral": "neu", "mixed": "mix"}

_CSS = """
:root{--bg:#0f1115;--card:#1a1d24;--ink:#e8eaed;--muted:#9aa0aa;--line:#2a2e37;
--pos:#2ea043;--neg:#e5534b;--neu:#6b7280;--mix:#d2992b;--accent:#4c8bf5;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC",
"Hiragino Sans GB","Microsoft YaHei",sans-serif;line-height:1.55;}
.wrap{max-width:880px;margin:0 auto;padding:0 16px 64px;}
header{position:sticky;top:0;background:rgba(15,17,21,.92);backdrop-filter:blur(8px);
border-bottom:1px solid var(--line);padding:14px 16px;z-index:9;}
header .wrap{padding:0;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;}
h1{font-size:18px;margin:0;}
.upd{color:var(--muted);font-size:12px;}
h2{font-size:16px;margin:28px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line);}
.note{color:var(--muted);font-size:12.5px;}
.stats{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0;}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:10px 14px;flex:1;min-width:120px;}
.stat .n{font-size:22px;font-weight:700;}
.stat .l{color:var(--muted);font-size:12px;}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:14px 16px;margin:10px 0;}
.row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
.co{font-weight:700;font-size:15px;}
.tk{font:600 11px/1 ui-monospace,monospace;background:#11141a;border:1px solid var(--line);
color:var(--accent);padding:3px 6px;border-radius:6px;}
.date{color:var(--muted);font-size:12px;margin-left:auto;}
.badge{font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid transparent;}
.pos{background:rgba(46,160,67,.15);color:#5fd97a;}
.neg{background:rgba(229,83,75,.15);color:#ff8079;}
.neu{background:rgba(107,114,128,.18);color:#b8bdc7;}
.mix{background:rgba(210,153,43,.16);color:#e9bd64;}
.chip{font-size:11px;color:var(--muted);background:#11141a;border:1px solid var(--line);
padding:2px 7px;border-radius:6px;}
.stars{color:#e9bd64;font-size:12px;letter-spacing:1px;}
blockquote{margin:10px 0 8px;padding:8px 12px;border-left:3px solid var(--accent);
background:#11141a;border-radius:0 8px 8px 0;font-size:14px;}
.zh{margin:6px 0 8px;padding:8px 12px;border-left:3px solid #d2992b;
background:#15130d;border-radius:0 8px 8px 0;font-size:13.5px;color:#e6d8b8;}
.zh b{color:#e9bd64;font-weight:600;}
a{color:var(--accent);text-decoration:none;} a:hover{text-decoration:underline;}
.src{font-size:12px;}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px;display:block;
overflow-x:auto;}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap;}
th{color:var(--muted);font-weight:600;}
.disc{background:#1a1410;border:1px solid #3a2a18;color:#e9c98f;border-radius:10px;
padding:12px 14px;font-size:12.5px;margin:16px 0;}
footer{margin-top:36px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);
padding-top:16px;}
.empty{color:var(--muted);padding:8px 0;}
"""


def _esc(s: str) -> str:
    return html.escape(str(s or ""))


def _stars(score: int) -> str:
    score = max(0, min(5, int(score or 0)))
    return "★" * score + "☆" * (5 - score)


def _parse_date(s: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def _card(m: Mention) -> str:
    sclass = _SENTI_CLASS.get(m.sentiment_toward_company, "neu")
    senti = _SENTI_ZH.get(m.sentiment_toward_company, m.sentiment_toward_company)
    policy = _POLICY_ZH.get(m.policy_angle, m.policy_angle)
    ticker = f'<span class="tk">{_esc(m.ticker_if_public)}</span>' if m.ticker_if_public else ""
    themes = "".join(f'<span class="chip">{_esc(t)}</span>' for t in m.theme_tags)
    src = (f'<a class="src" href="{_esc(m.source_url)}" target="_blank" rel="noopener">来源 ↗</a>'
           if m.source_url else "")
    zh = (f'<div class="zh"><b>中译：</b>{_esc(m.exact_quote_zh)}</div>'
          if m.exact_quote_zh else "")
    return f"""<div class="card">
  <div class="row">
    <span class="co">{_esc(m.normalized_company_name)}</span>{ticker}
    <span class="date">{_esc(m.date)}</span>
  </div>
  <div class="row" style="margin-top:6px">
    <span class="badge {sclass}">{_esc(senti)}</span>
    <span class="chip">{_esc(policy)}</span>
    {themes}
    <span class="stars" title="投资相关性 {m.investment_relevance_score}/5">{_stars(m.investment_relevance_score)}</span>
  </div>
  <blockquote>{_esc(m.exact_quote)}</blockquote>
  {zh}
  <div class="row"><span class="note">{_esc(m.source_type)} · 置信度 {m.confidence_score}/5</span> {src}</div>
</div>"""


def _trade_card(t) -> str:
    buy = t.action == "buy"
    cls = "pos" if buy else "neg"
    label = "买入" if buy else "卖出"
    tk = f'<span class="tk">{_esc(t.ticker)}</span>' if t.ticker else ""
    uns = '<span class="chip">unsolicited</span>' if getattr(t, "unsolicited", False) else ""
    note = f'<div class="note" style="margin-top:8px">{_esc(t.note)}</div>' if t.note else ""
    src = (f'<a class="src" href="{_esc(t.source_url)}" target="_blank" rel="noopener">来源 ↗</a>'
           if t.source_url else "")
    return f"""<div class="card">
  <div class="row">
    <span class="badge {cls}">{label}</span>
    <span class="co">{_esc(t.company)}</span>{tk}
    <span class="date">{_esc(t.date_note or t.date)}</span>
  </div>
  <div class="row" style="margin-top:6px"><span class="chip">金额 {_esc(t.amount)}</span>{uns}</div>
  {note}
  <div class="row" style="margin-top:6px">{src}</div>
</div>"""


def build_html(mentions: list[Mention], run_date: dt.date | None = None,
               trades: list | None = None) -> str:
    run_date = run_date or dt.datetime.utcnow().date()
    trades = trades or []
    dated = [(m, _parse_date(m.date)) for m in mentions]
    dated = [(m, d) for m, d in dated if d]
    dated.sort(key=lambda x: x[1], reverse=True)

    total = len(mentions)
    companies = {m.normalized_company_name for m in mentions}
    last7 = run_date - dt.timedelta(days=7)
    last30 = run_date - dt.timedelta(days=30)
    week_count = sum(1 for _, d in dated if d >= last7)

    # Today's (run-day) mentions, else the most recent day that has any.
    today = [m for m, d in dated if d == run_date]
    latest_label, latest = "今日", today
    if not latest and dated:
        newest = dated[0][1]
        latest_label = f"最近提及（{newest}）"
        latest = [m for m, d in dated if d == newest]

    parts: list[str] = []
    A = parts.append
    A(f'<!doctype html><html lang="zh"><head><meta charset="utf-8">')
    A('<meta name="viewport" content="width=device-width,initial-scale=1">')
    A("<title>Trump 公司提及追踪</title>")
    A(f"<style>{_CSS}</style></head><body>")
    A('<header><div class="wrap"><h1>🇺🇸 Trump 公司提及追踪</h1>'
      f'<span class="upd">更新于 {run_date} (UTC) · 共 {total} 条</span></div></header>')
    A('<div class="wrap">')

    A(f'<div class="disc">⚠️ {_esc(DISCLAIMER)}</div>')

    A('<div class="stats">'
      f'<div class="stat"><div class="n">{total}</div><div class="l">总记录</div></div>'
      f'<div class="stat"><div class="n">{len(companies)}</div><div class="l">涉及公司</div></div>'
      f'<div class="stat"><div class="n">{week_count}</div><div class="l">近 7 天</div></div>'
      f'<div class="stat"><div class="n">{len(trades)}</div><div class="l">本人交易</div></div>'
      '</div>')

    # --- Trump's personal trades (OGE 278-T) ---
    if trades:
        A(f"<h2>💰 川普个人交易披露（OGE）· {len(trades)} 笔</h2>")
        A('<div class="disc">⚠️ 来自 Trump 的 OGE Form 278-T 申报。<b>金额为披露区间</b>(非精确值);'
          '此为 2026 Q1 的 AI 相关/大额交易<b>策展子集</b>(全季共 3,642 笔),约每季度更新。'
          '交易由其信托执行,时点与其公开言论/政策的关联仅供观察,不构成因果或投资建议。</div>')
        for t in trades:
            A(_trade_card(t))

    # --- today / latest ---
    A(f"<h2>{_esc(latest_label)}</h2>")
    if latest:
        for m in sorted(latest, key=lambda x: x.investment_relevance_score, reverse=True):
            A(_card(m))
    else:
        A('<div class="empty">暂无记录。</div>')

    # --- high relevance ---
    high = [m for m, d in dated if m.investment_relevance_score >= 4]
    A(f"<h2>高投资相关性（≥4）· {len(high)} 条</h2>")
    if high:
        for m in high[:30]:
            A(_card(m))
    else:
        A('<div class="empty">暂无评分 ≥4 的记录。</div>')

    # --- last 30 days feed ---
    recent = [m for m, d in dated if d >= last30]
    A(f"<h2>近 30 天（{len(recent)} 条）</h2>")
    if recent:
        for m in recent:
            A(_card(m))
    else:
        A('<div class="empty">近 30 天内没有提及具体公司（样本数据多为历史记录）。</div>')

    # --- by company ---
    counter = Counter(m.normalized_company_name for m in mentions)
    ticker_of = {m.normalized_company_name: m.ticker_if_public for m in mentions}
    last_of: dict[str, dt.date] = {}
    for m, d in dated:
        cur = last_of.get(m.normalized_company_name)
        if cur is None or d > cur:
            last_of[m.normalized_company_name] = d
    trades_by_co: dict[str, list] = {}
    for t in trades:
        trades_by_co.setdefault(t.company, []).append(t)
    A("<h2>按公司（提及 × 本人交易）</h2>")
    A("<table><tr><th>公司</th><th>Ticker</th><th>提及次数</th><th>最近一次</th>"
      "<th>本人交易(OGE)</th></tr>")
    for name, cnt in counter.most_common():
        tl = trades_by_co.get(name, [])
        tcell = "；".join(
            f'{"🟢买" if x.action == "buy" else "🔴卖"} {_esc(x.amount)}·{_esc(x.date_note or x.date)}'
            for x in tl) or "—"
        A(f"<tr><td>{_esc(name)}</td><td>{_esc(ticker_of.get(name,'') or '—')}</td>"
          f"<td>{cnt}</td><td>{_esc(last_of.get(name,''))}</td><td>{tcell}</td></tr>")
    A("</table>")

    A('<footer>'
      '数据源：Trump 的 Truth Social 公开存档（每日抓取）+ 人工核验来源。'
      ' · <a href="data.jsonl" download>下载原始数据 (JSONL)</a>'
      f'<div class="disc" style="margin-top:12px">{_esc(DISCLAIMER)}</div>'
      '</footer>')
    A("</div></body></html>")
    return "\n".join(parts)


def build_site(
    mentions: list[Mention],
    site_dir: Path = SITE_DIR,
    run_date: dt.date | None = None,
    trades: list | None = None,
) -> Path:
    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text(
        build_html(mentions, run_date, trades), encoding="utf-8"
    )
    with (site_dir / "data.jsonl").open("w", encoding="utf-8") as fh:
        for m in mentions:
            fh.write(json.dumps(m.to_json_obj(), ensure_ascii=False) + "\n")
    return site_dir / "index.html"
