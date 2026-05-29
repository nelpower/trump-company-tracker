"""Render a Markdown research report from the deduped mentions."""
from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict

from src.config import POLICY_ANGLES, REPORT_OUT, THEME_TAGS
from src.models import Mention

DISCLAIMER = (
    "> **重要声明 / Disclaimer**：本报告仅收集与整理特朗普公开言论中对具体公司的提及，"
    "用于投资研究的*注意力/政策线索*追踪。**特朗普的言论本身不构成任何买入或卖出建议**，"
    "言论与实际订单、合同、财报、估值之间往往存在巨大差距，且可能反复。任何投资决策必须"
    "结合公司财报、订单、现金流、估值与产业逻辑独立验证。数据由启发式规则自动抽取，"
    "可能存在误判，使用前请人工复核 `exact_quote` 与 `source_url`。"
)

# theme -> (投资线索 hint, 风险 hint) — generic, theme-level, conservative.
_THEME_HINTS: dict[str, tuple[str, str]] = {
    "semiconductor": ("半导体制造/设备/材料/代工产业链关注度上升",
                      "资本开支兑现周期长、产能爬坡与地缘出口管制风险"),
    "AI": ("AI 算力、模型、应用及配套基础设施需求叙事",
           "估值已计入高增长预期，落地与变现节奏不确定"),
    "data_center": ("数据中心、电力、冷却、网络与服务器供应链",
                    "电力/土地瓶颈与超额建设(overbuild)风险"),
    "defense": ("国防订单与防务预算受益方",
                "依赖政府预算与采购周期，政治不确定性高"),
    "aerospace": ("航空航天整机/分包/维修产业链",
                  "项目延期、成本超支与固定价合同亏损风险"),
    "energy": ("能源生产、电网、核能与传统油气",
               "商品价格波动与政策反复风险"),
    "manufacturing": ("美国本土制造、回流与配套设备/建设",
                      "补贴依赖、用工成本与达产不及预期风险"),
    "telecom": ("通信设备与网络基础设施",
                "运营商资本开支周期与竞争格局风险"),
    "auto": ("整车/零部件/电动化转型",
             "需求周期性、价格战与补贴退坡风险"),
    "consumer": ("品牌认知与消费需求边际变化",
                 "言论对基本面影响有限，多为短期情绪/公关层面"),
    "cloud": ("云计算与企业 IT 支出", "竞争激烈、资本开支高企"),
    "infrastructure": ("基建相关材料/工程/设备", "依赖立法拨款与执行节奏"),
    "other": ("提及本身代表政策注意力", "投资含义需进一步确认"),
}


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def _clip(text: str, n: int = 90) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _parse_date(s: str) -> dt.date | None:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def build_report(mentions: list[Mention], today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    total = len(mentions)
    lines: list[str] = []
    add = lines.append

    add("# Trump Company Mention Tracker — 研究报告")
    add("")
    add(f"*生成时间：{dt.datetime.now():%Y-%m-%d %H:%M}　|　记录总数：**{total}***")
    add("")
    add(DISCLAIMER)
    add("")

    if total == 0:
        add("\n_当前没有任何记录。请在 `data/sources.yaml` 添加来源后重新运行 pipeline。_")
        return "\n".join(lines)

    # ---- 时间分布 ------------------------------------------------------- #
    by_year: Counter = Counter()
    by_month: Counter = Counter()
    for m in mentions:
        d = _parse_date(m.date)
        if d:
            by_year[d.year] += 1
            by_month[f"{d.year}-{d.month:02d}"] += 1
    add("## 1. 时间分布")
    add("")
    add("**按年份：**")
    add("")
    add(_md_table(["年份", "mentions"],
                  [[y, by_year[y]] for y in sorted(by_year)]))
    add("")
    add("**按月份：**")
    add("")
    add(_md_table(["月份", "mentions"],
                  [[mth, by_month[mth]] for mth in sorted(by_month)]))
    add("")

    # ---- Top 20 公司 ---------------------------------------------------- #
    comp_counter: Counter = Counter(m.normalized_company_name for m in mentions)
    ticker_of = {m.normalized_company_name: m.ticker_if_public for m in mentions}
    add("## 2. 被提及最多的公司 (Top 20)")
    add("")
    add(_md_table(
        ["#", "公司", "ticker", "mentions"],
        [[i + 1, name, ticker_of.get(name, "") or "—", cnt]
         for i, (name, cnt) in enumerate(comp_counter.most_common(20))],
    ))
    add("")

    # ---- 情绪分布 ------------------------------------------------------- #
    senti = Counter(m.sentiment_toward_company for m in mentions)
    add("## 3. 情绪分布 (sentiment_toward_company)")
    add("")
    add(_md_table(["情绪", "数量", "占比"],
                  [[s, senti[s], f"{senti[s] / total:.0%}"]
                   for s in ("positive", "negative", "neutral", "mixed")
                   if senti[s]]))
    add("")

    # ---- 主题分布 ------------------------------------------------------- #
    theme_counter: Counter = Counter()
    for m in mentions:
        for t in m.theme_tags:
            theme_counter[t] += 1
    add("## 4. 主题分布 (theme_tags)")
    add("")
    add(_md_table(["主题", "出现次数"],
                  [[t, theme_counter[t]] for t in THEME_TAGS if theme_counter[t]]))
    add("")

    # ---- 政策角度分布 --------------------------------------------------- #
    policy_counter = Counter(m.policy_angle for m in mentions)
    add("## 5. 政策角度分布 (policy_angle)")
    add("")
    add(_md_table(["政策角度", "数量"],
                  [[p, policy_counter[p]] for p in sorted(POLICY_ANGLES)
                   if policy_counter[p]]))
    add("")

    # ---- 最近 30 天 ----------------------------------------------------- #
    cutoff = today - dt.timedelta(days=30)
    first_seen: dict[str, dt.date] = {}
    for m in mentions:
        d = _parse_date(m.date)
        if not d:
            continue
        if m.normalized_company_name not in first_seen or d < first_seen[m.normalized_company_name]:
            first_seen[m.normalized_company_name] = d
    recent = sorted(
        [(name, d) for name, d in first_seen.items() if d >= cutoff],
        key=lambda x: x[1], reverse=True,
    )
    add(f"## 6. 最近 30 天新增公司 mentions (相对运行日 {today})")
    add("")
    if recent:
        add(_md_table(["公司", "首次提及日期"], [[n, str(d)] for n, d in recent]))
    else:
        add("_最近 30 天内没有新提及的公司（样本数据多为历史记录，属预期）。_")
    add("")

    # ---- 高投资相关性 -------------------------------------------------- #
    high = sorted(
        [m for m in mentions if m.investment_relevance_score >= 4],
        key=lambda m: (m.investment_relevance_score, m.date or ""), reverse=True,
    )
    add("## 7. 高投资相关性记录 (investment_relevance_score ≥ 4)")
    add("")
    if high:
        add(_md_table(
            ["日期", "公司", "ticker", "评分", "情绪", "政策角度", "原话(节选)", "来源"],
            [[m.date, m.normalized_company_name, m.ticker_if_public or "—",
              m.investment_relevance_score, m.sentiment_toward_company,
              m.policy_angle, _clip(m.exact_quote),
              f"[link]({m.source_url})" if m.source_url else "—"]
             for m in high],
        ))
    else:
        add("_暂无评分≥4 的记录。_")
    add("")

    # ---- 每家公司中文总结 ---------------------------------------------- #
    add("## 8. 每家公司中文总结")
    add("")
    per_company: dict[str, list[Mention]] = defaultdict(list)
    for m in mentions:
        per_company[m.normalized_company_name].append(m)

    for name in sorted(per_company,
                       key=lambda n: (-len(per_company[n]), n)):
        recs = sorted(per_company[name], key=lambda m: m.date or "")
        sample = recs[0]
        tk = sample.ticker_if_public or "未上市/未知"
        status = sample.company_status
        themes = sorted({t for m in recs for t in m.theme_tags})
        policies = sorted({m.policy_angle for m in recs if m.policy_angle != "unknown"})
        sentiments = sorted({m.sentiment_toward_company for m in recs})
        max_rel = max(m.investment_relevance_score for m in recs)

        lead_bits, risk_bits = [], []
        for t in themes:
            hint = _THEME_HINTS.get(t)
            if hint:
                lead_bits.append(hint[0])
                risk_bits.append(hint[1])
        # de-dup while preserving order
        lead = "；".join(dict.fromkeys(lead_bits)) or "提及本身代表政策注意力"
        risk = "；".join(dict.fromkeys(risk_bits)) or "投资含义需进一步确认"

        add(f"### {name}　（{tk}，{status}）")
        add("")
        add(f"- **提及次数 / 时间**：{len(recs)} 次，"
            f"{recs[0].date} ～ {recs[-1].date}")
        add(f"- **语境与情绪**：{ '、'.join(sentiments) }；"
            f"主题 {('、'.join(themes)) or '其他'}")
        add(f"- **政策含义**：{ '、'.join(_zh_policies(policies)) or '暂不明确' }")
        add(f"- **可能投资线索**：{lead}（最高相关性评分 {max_rel}/5）")
        add(f"- **风险**：{risk}")
        add(f"- **代表性原话**：")
        for m in recs[:3]:
            url = f" — [来源]({m.source_url})" if m.source_url else ""
            add(f"  - {m.date}：「{_clip(m.exact_quote, 160)}」{url}")
        add("")

    add("---")
    add("")
    add(DISCLAIMER)
    add("")
    return "\n".join(lines)


def _zh_policies(policies: list[str]) -> list[str]:
    from src.score_relevance import _POLICY_ZH

    return [_POLICY_ZH.get(p, p) for p in policies]


def write_report(mentions: list[Mention], path=REPORT_OUT) -> str:
    text = build_report(mentions)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text
