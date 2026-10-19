"""Render the collected A-share snapshot as an HTML dashboard and a
Markdown briefing.  No third-party template engine is required.
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any

SOURCE_LABELS = {
    "ths": "同花顺",
    "em": "东方财富",
    "xq": "雪球",
}
HOT_SOURCE_ORDER = ("ths", "em", "xq")

WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def num(value: Any, digits: int = 2, dash: str = "—") -> str:
    try:
        if value is None:
            return dash
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return dash


def signed(value: Any, digits: int = 2, suffix: str = "") -> str:
    try:
        if value is None:
            return "—"
        return f"{float(value):+,.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "—"


def pct(value: Any, digits: int = 2) -> str:
    try:
        if value is None:
            return "—"
        return f"{float(value):+.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def pct_class(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "flat"
    if number > 0.0001:
        return "up"
    if number < -0.0001:
        return "down"
    return "flat"


def fmt_amount(value: Any, dash: str = "—") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return dash
    sign = "-" if number < 0 else ""
    number = abs(number)
    if number >= 1e12:
        return f"{sign}{number / 1e12:,.2f}万亿"
    if number >= 1e8:
        return f"{sign}{number / 1e8:,.2f}亿"
    if number >= 1e4:
        return f"{sign}{number / 1e4:,.2f}万"
    return f"{sign}{number:,.0f}"


def fmt_amount_signed(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return ("+" if number > 0 else "") + fmt_amount(number)


def fmt_compact(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if abs(number) >= 1e8:
        return f"{number / 1e8:,.2f}亿"
    if abs(number) >= 1e4:
        return f"{number / 1e4:,.1f}万"
    if abs(number) >= 1000:
        return f"{number:,.0f}"
    return f"{number:,.1f}"


def fmt_lots(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number >= 1e8:
        return f"{number / 1e8:,.2f}亿手"
    if number >= 1e4:
        return f"{number / 1e4:,.2f}万手"
    return f"{number:,.0f}手"


def weekday_cn(date_text: str) -> str:
    try:
        return WEEKDAYS[datetime.strptime(date_text[:10], "%Y-%m-%d").weekday()]
    except (TypeError, ValueError):
        return ""


def board_text(limit: dict[str, Any] | None) -> str:
    if not limit:
        return "—"
    high_days = str(limit.get("high_days") or "").strip()
    if high_days:
        return high_days
    days = limit.get("days")
    boards = limit.get("board_count")
    if days and boards:
        return f"{days}天{boards}板"
    if boards:
        return "首板" if int(boards) == 1 else f"{int(boards)}连板"
    return "涨停"


def limit_badge(row: dict[str, Any], with_reason: bool = True) -> str:
    limit = row.get("limit_up")
    if not limit and row.get("reason"):
        limit = row
    if not limit:
        return '<span class="muted">—</span>'
    label = board_text(limit)
    reason = str(limit.get("reason") or "").strip()
    parts = [f'<span class="tag limit">{esc(label)}</span>']
    if with_reason and reason:
        short = reason if len(reason) <= 30 else reason[:29] + "…"
        parts.append(f'<span class="reason" title="{esc(reason)}">{esc(short)}</span>')
    return '<span class="limit-cell">' + "".join(parts) + "</span>"


def rank_cell(rank: int, change: Any = None) -> str:
    klass = " rank-top" if rank <= 3 else ""
    body = f'<span class="rank{klass}">{rank}</span>'
    if change not in (None, 0, ""):
        try:
            delta = int(change)
        except (TypeError, ValueError):
            delta = 0
        if delta:
            cls = "up" if delta > 0 else "down"
            arrow = "↑" if delta > 0 else "↓"
            body += f'<span class="rank-chg {cls}">{arrow}{abs(delta)}</span>'
    return body


def heat_cell(value: Any) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    width = max(0.0, min(100.0, number))
    return (
        '<div class="heat">'
        f'<span class="heat-bar"><i style="width:{width:.1f}%"></i></span>'
        f'<span class="heat-num">{number:.1f}</span>'
        "</div>"
    )


def change_class(value: Any) -> str:
    return pct_class(value)


def delta_cell(value: Any, digits: int = 2, suffix: str = "%", reverse: bool = False) -> str:
    if value is None:
        return '<span class="muted">—</span>'
    cls = pct_class(value)
    if reverse:
        cls = "down" if cls == "up" else "up" if cls == "down" else "flat"
    return f'<span class="{cls}">{signed(value, digits, suffix)}</span>'


# ---------------------------------------------------------------------------
# Small render pieces
# ---------------------------------------------------------------------------
def sparkline(values: list[Any], positive: bool, uid: str) -> str:
    points: list[tuple[float, float]] = []
    clean: list[float] = []
    for value in values or []:
        try:
            clean.append(float(value))
        except (TypeError, ValueError):
            continue
    if len(clean) < 2:
        return '<div class="spark-empty">走势数据不足</div>'
    width, height, pad = 260.0, 64.0, 4.0
    low, high = min(clean), max(clean)
    if abs(high - low) < 1e-9:
        high = low + 1.0
    for index, value in enumerate(clean):
        x = pad + index * (width - pad * 2) / (len(clean) - 1)
        y = height - pad - (value - low) / (high - low) * (height - pad * 2)
        points.append((x, y))
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = f"{pad:.1f},{height - pad:.1f} {line} {width - pad:.1f},{height - pad:.1f}"
    color = "#ff4d5e" if positive else "#16c784"
    return (
        f'<svg class="spark" viewBox="0 0 {width:.0f} {height:.0f}" preserveAspectRatio="none">'
        f'<defs><linearGradient id="g-{uid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}" stop-opacity=".30"/>'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/>'
        "</linearGradient></defs>"
        f'<polygon points="{area}" fill="url(#g-{uid})"/>'
        f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2" '
        'stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{points[-1][0]:.1f}" cy="{points[-1][1]:.1f}" r="3" fill="{color}"/>'
        "</svg>"
    )


def empty_state(text: str = "本期暂无数据") -> str:
    return f'<div class="empty"><span>∅</span>{esc(text)}</div>'


def stock_name_cell(row: dict[str, Any]) -> str:
    name = row.get("name") or row.get("code") or "—"
    sub = row.get("sub_sector") or ""
    extra = f'<small>{esc(sub)}</small>' if sub and sub != "未分类" else ""
    return f'<div class="name-cell"><b>{esc(name)}</b>{extra}</div>'


def sector_cell(row: dict[str, Any]) -> str:
    sector = row.get("sector") or "未分类"
    sub = row.get("sub_sector") or ""
    title = f'{sector} / {sub}' if sub else str(sector)
    klass = " sector-unknown" if sector == "未分类" else ""
    return f'<span class="sector{klass}" title="{esc(title)}">{esc(sector)}</span>'


def stock_search_text(row: dict[str, Any]) -> str:
    parts = [
        str(row.get("code") or ""),
        str(row.get("name") or ""),
        str(row.get("sector") or ""),
        str(row.get("sub_sector") or ""),
    ]
    return " ".join(parts).lower()


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
def top_table(rows: list[dict[str, Any]], empty_text: str = "本期暂无数据") -> str:
    if not rows:
        return empty_state(empty_text)
    body: list[str] = []
    for index, row in enumerate(rows, 1):
        limit = row.get("limit_up")
        body.append(
            f'<tr data-search="{esc(stock_search_text(row))}">'
            f'<td class="l">{rank_cell(index)}</td>'
            f'<td class="l"><span class="code">{esc(row.get("code", ""))}</span></td>'
            f"<td class=\"l\">{stock_name_cell(row)}</td>"
            f'<td class="l">{sector_cell(row)}</td>'
            f'<td>{num(row.get("price"), 2)}</td>'
            f'<td class="{change_class(row.get("pct"))}">{pct(row.get("pct"))}</td>'
            f'<td>{fmt_amount(row.get("amount"))}</td>'
            f'<td>{num(row.get("turnover"), 2)}%</td>'
            f'<td>{num(row.get("amplitude"), 2)}%</td>'
            f'<td class="{change_class(row.get("main_net_inflow"))}">'
            f'{fmt_amount_signed(row.get("main_net_inflow"))}</td>'
            f'<td class="l">{limit_badge(row)}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="data-table stock-table">'
        "<thead><tr>"
        '<th class="l">#</th><th class="l">代码</th><th class="l">名称</th>'
        '<th class="l">所属板块</th><th>现价</th><th>涨跌幅</th>'
        "<th>成交额</th><th>换手率</th><th>振幅</th><th>主力净流入</th>"
        '<th class="l">涨停 / 几天几板</th>'
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def hot_table(rows: list[dict[str, Any]], source: str) -> str:
    if not rows:
        return empty_state("该来源本期无数据")
    body: list[str] = []
    for index, row in enumerate(rows, 1):
        extras: list[str] = []
        if source == "ths":
            if row.get("heat"):
                extras.append(f'<span class="hot-num">{fmt_compact(row.get("heat"))}</span>')
            for tag in (row.get("concept_tags") or [])[:2]:
                extras.append(f'<span class="tag">{esc(tag)}</span>')
        elif source == "em":
            extras.append('<span class="tag">人气榜</span>')
            change = row.get("rank_change")
            if change not in (None, 0):
                cls = "up" if int(change) > 0 else "down"
                arrow = "↑" if int(change) > 0 else "↓"
                extras.append(f'<span class="{cls} rank-chg">{arrow}{abs(int(change))}</span>')
        elif source == "xq":
            if row.get("heat"):
                extras.append(f'<span class="hot-num">热度 {fmt_compact(row.get("heat"))}</span>')
        meta = "".join(extras) or '<span class="muted">—</span>'
        body.append(
            f'<tr data-search="{esc(stock_search_text(row))}">'
            f'<td class="l">{rank_cell(index, row.get("rank_change"))}</td>'
            f'<td class="l"><span class="code">{esc(row.get("code", ""))}</span></td>'
            f"<td class=\"l\">{stock_name_cell(row)}</td>"
            f'<td class="l">{sector_cell(row)}</td>'
            f'<td class="{change_class(row.get("pct"))}">{pct(row.get("pct"))}</td>'
            f'<td>{fmt_amount(row.get("amount"))}</td>'
            f'<td>{num(row.get("turnover"), 2)}%</td>'
            f'<td>{num(row.get("amplitude"), 2)}%</td>'
            f'<td class="l meta-cell">{meta}</td>'
            f'<td class="l">{limit_badge(row)}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="data-table stock-table">'
        "<thead><tr>"
        '<th class="l">#</th><th class="l">代码</th><th class="l">名称</th>'
        '<th class="l">所属板块</th><th>涨跌幅</th><th>成交额</th>'
        '<th>换手率</th><th>振幅</th><th class="l">热度 / 标签</th>'
        '<th class="l">涨停 / 几天几板</th>'
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def resonance_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return empty_state("本期没有跨平台同时上榜的个股")
    body: list[str] = []
    for index, row in enumerate(rows, 1):
        ranks = row.get("ranks") or {}
        rank_text = " · ".join(
            f'{SOURCE_LABELS.get(key, key)}#{value}'
            for key, value in sorted(ranks.items(), key=lambda item: item[1])
        )
        body.append(
            f'<tr data-search="{esc(stock_search_text(row))}">'
            f'<td class="l">{rank_cell(index)}</td>'
            f'<td class="l"><span class="code">{esc(row.get("code", ""))}</span></td>'
            f'<td class="l">{stock_name_cell(row)}</td>'
            f'<td class="l">{sector_cell(row)}</td>'
            f'<td><span class="res-count">{int(row.get("source_count", 0))}</span></td>'
            f'<td class="l ranks">{esc(rank_text)}</td>'
            f'<td class="{change_class(row.get("pct"))}">{pct(row.get("pct"))}</td>'
            f'<td>{fmt_amount(row.get("amount"))}</td>'
            f'<td class="l">{limit_badge(row, True)}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="data-table">'
        "<thead><tr>"
        '<th class="l">#</th><th class="l">代码</th><th class="l">名称</th>'
        '<th class="l">所属板块</th><th>上榜来源</th><th class="l">各榜排名</th>'
        '<th>涨跌幅</th><th>成交额</th><th class="l">涨停 / 几天几板</th>'
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def sector_table(rows: list[dict[str, Any]], metric: str) -> str:
    if not rows:
        return empty_state("板块聚合数据不足（需至少 3 只同行业个股）")
    body: list[str] = []
    for index, row in enumerate(rows, 1):
        hot_names = "、".join(row.get("hot_names") or []) or "—"
        limit_text = f'{int(row.get("limit_count", 0))}'
        if row.get("board_count"):
            limit_text += f'<small>含{int(row.get("board_count", 0))}只连板</small>'
        body.append(
            '<tr data-search="' + esc(
                " ".join(
                    [
                        str(row.get("name") or ""),
                        str(row.get("leader") or ""),
                        str(row.get("hot_names") or ""),
                    ]
                ).lower()
            ) + '">'
            f'<td class="l">{rank_cell(index)}</td>'
            f'<td class="l"><b>{esc(row.get("name", ""))}</b></td>'
            f'<td class="{change_class(row.get("avg_pct"))}">{pct(row.get("avg_pct"))}</td>'
            f'<td>{fmt_amount(row.get("amount"))}</td>'
            f'<td class="{change_class(row.get("net_inflow"))}">{fmt_amount_signed(row.get("net_inflow"))}</td>'
            f"<td>{heat_cell(row.get('heat'))}</td>"
            f'<td class="l">{limit_text}</td>'
            f'<td class="l">{esc(row.get("leader", "—"))} '
            f'<span class="{change_class(row.get("leader_pct"))}">'
            f'{pct(row.get("leader_pct"))}</span></td>'
            f'<td><span class="up">{int(row.get("up_count", 0))}</span> / '
            f'<span class="down">{int(row.get("down_count", 0))}</span></td>'
            f'<td class="l hot-names" title="{esc(hot_names)}">{esc(hot_names)}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="data-table sector-table">'
        "<thead><tr>"
        '<th class="l">#</th><th class="l">板块（东财二级）</th><th>平均涨跌</th>'
        "<th>成交额</th><th>主力净流入</th><th>热度</th><th class=\"l\">涨停 / 连板</th>"
        '<th class="l">领涨股</th><th>涨 / 跌</th><th class="l">热榜个股</th>'
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def theme_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return empty_state("淘股吧题材榜本期无数据")
    body: list[str] = []
    for index, row in enumerate(rows[:30], 1):
        def leader(item: Any, klass: str = "tag") -> str:
            if not item:
                return '<span class="muted">—</span>'
            return (
                f'<span class="{klass}">{esc(item.get("name", ""))}</span>'
                f'<small class="code">{esc(item.get("code", ""))}</small>'
            )

        hot_flag = row.get("hot_flag")
        hot_flag_html = f'<span class="mini-flag">{esc(hot_flag)}</span>' if hot_flag else ""
        body.append(
            '<tr data-search="' + esc(
                " ".join(
                    [
                        str(row.get("name") or ""),
                        str((row.get("human") or {}).get("name") or ""),
                        str((row.get("mid") or {}).get("name") or ""),
                        str((row.get("day") or {}).get("name") or ""),
                    ]
                ).lower()
            ) + '">'
            f'<td class="l">{rank_cell(index)}</td>'
            f'<td class="l"><b>{esc(row.get("name", ""))}</b>{hot_flag_html}</td>'
            f'<td>{num(row.get("heat"), 0)}</td>'
            f'<td class="{change_class(row.get("pct"))}">{pct(row.get("pct"))}</td>'
            f'<td>{int(row.get("limit_up", 0))}</td>'
            f'<td><span class="up">{int(row.get("up", 0))}</span> / '
            f'<span class="down">{int(row.get("down", 0))}</span></td>'
            f'<td>{num(row.get("ratio"), 1)}%</td>'
            f'<td class="l">{leader(row.get("human"))}</td>'
            f'<td class="l">{leader(row.get("mid"))}</td>'
            f'<td class="l">{leader(row.get("day"))}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="data-table">'
        "<thead><tr>"
        '<th class="l">#</th><th class="l">题材</th><th>热度值</th><th>涨跌幅</th>'
        '<th>涨停</th><th>涨 / 跌</th><th>资金占比</th>'
        '<th class="l">人气龙头</th><th class="l">中军</th><th class="l">日内龙</th>'
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def limit_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return empty_state("涨停池本期无数据")
    body: list[str] = []
    for index, row in enumerate(rows, 1):
        body.append(
            f'<tr data-search="{esc(stock_search_text(row))}">'
            f'<td class="l">{rank_cell(index)}</td>'
            f'<td class="l"><span class="code">{esc(row.get("code", ""))}</span></td>'
            f'<td class="l">{stock_name_cell(row)}</td>'
            f'<td class="l">{sector_cell(row)}</td>'
            f'<td>{num(row.get("price"), 2)}</td>'
            f'<td class="up">{pct(row.get("pct"))}</td>'
            f'<td>{fmt_amount(row.get("amount"))}</td>'
            f'<td>{num(row.get("turnover"), 2)}%</td>'
            f'<td>{num(row.get("amplitude"), 2)}%</td>'
            f'<td class="l"><span class="tag limit">{esc(board_text(row))}</span></td>'
            f'<td class="l reason-cell" title="{esc(row.get("reason", ""))}">'
            f'{esc(row.get("reason") or "—")}</td>'
            f'<td>{esc(row.get("first_time") or "—")}</td>'
            f'<td>{esc(row.get("last_time") or "—")}</td>'
            f'<td>{int(row.get("open_num", 0))}</td>'
            f'<td>{fmt_amount(row.get("order_amount"))}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap table-tall"><table class="data-table">'
        "<thead><tr>"
        '<th class="l">#</th><th class="l">代码</th><th class="l">名称</th>'
        '<th class="l">所属板块</th><th>现价</th><th>涨跌幅</th><th>成交额</th>'
        '<th>换手率</th><th>振幅</th><th class="l">几天几板</th>'
        '<th class="l">涨停原因</th><th>首封</th><th>最后封</th><th>开板</th>'
        '<th>封单额</th>'
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
def render_index_cards(indexes: list[dict[str, Any]]) -> str:
    if not indexes:
        return empty_state("指数行情获取失败")
    cards: list[str] = []
    for position, item in enumerate(indexes):
        cls = pct_class(item.get("pct"))
        uid = f"idx{position}"
        amount_delta = item.get("amount_change_pct")
        volume_delta = item.get("volume_change_pct")
        cards.append(
            '<article class="index-card">'
            '<div class="index-head">'
            f'<span class="idx-name">{esc(item.get("name", ""))}</span>'
            f'<span class="idx-code">{esc(item.get("code", ""))} · {esc(item.get("short_name", ""))}</span>'
            "</div>"
            '<div class="idx-main">'
            f'<span class="idx-price {cls}">{num(item.get("price"), 2)}</span>'
            f'<span class="idx-pct {cls}">{pct(item.get("pct"))}</span>'
            "</div>"
            f'<div class="idx-change {cls}">{signed(item.get("change"), 2)}</div>'
            f'{sparkline(item.get("spark") or [], cls != "down", uid)}'
            '<div class="idx-stats">'
            f'<div><span>成交额</span><b>{fmt_amount(item.get("amount"))}</b></div>'
            f'<div><span>较昨日成交额</span><b class="{change_class(amount_delta)}">'
            f'{delta_cell(amount_delta)}</b></div>'
            f'<div><span>成交量</span><b>{fmt_lots(item.get("volume_lots"))}</b></div>'
            f'<div><span>较昨日成交量</span><b class="{change_class(volume_delta)}">'
            f'{delta_cell(volume_delta)}</b></div>'
            f'<div><span>振幅</span><b>{num(item.get("amplitude"), 2)}%</b></div>'
            f'<div><span>最高 / 最低</span><b>{num(item.get("high"), 2)} / {num(item.get("low"), 2)}</b></div>'
            "</div>"
            "</article>"
        )
    return '<div class="index-grid">' + "".join(cards) + "</div>"


def render_index_table(indexes: list[dict[str, Any]]) -> str:
    if not indexes:
        return empty_state("指数行情获取失败")
    body: list[str] = []
    for item in indexes:
        body.append(
            "<tr>"
            f'<td class="l"><b>{esc(item.get("name", ""))}</b>'
            f'<small class="code">{esc(item.get("symbol", ""))}</small></td>'
            f'<td>{num(item.get("price"), 2)}</td>'
            f'<td class="{change_class(item.get("pct"))}">{pct(item.get("pct"))}</td>'
            f'<td>{fmt_amount(item.get("amount"))}</td>'
            f'<td>{fmt_amount(item.get("prev_amount"))}</td>'
            f'<td>{delta_cell(item.get("amount_change_pct"))}</td>'
            f'<td>{fmt_lots(item.get("volume_lots"))}</td>'
            f'<td>{fmt_lots(item.get("prev_volume_lots"))}</td>'
            f'<td>{delta_cell(item.get("volume_change_pct"))}</td>'
            f'<td>{num(item.get("amplitude"), 2)}%</td>'
            f'<td>{num(item.get("high"), 2)} / {num(item.get("low"), 2)}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="data-table">'
        "<thead><tr>"
        '<th class="l">指数</th><th>收盘</th><th>涨跌幅</th><th>成交额</th>'
        "<th>昨日成交额</th><th>成交额变化</th><th>成交量</th><th>昨日成交量</th>"
        "<th>成交量变化</th><th>振幅</th><th>最高 / 最低</th>"
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>"
    )


def index_comment(data: dict[str, Any]) -> str:
    by_symbol = {item.get("symbol"): item for item in data.get("indexes") or []}
    fragments: list[str] = []
    for label, symbol in (("沪市", "SH000001"), ("深市", "SZ399001")):
        item = by_symbol.get(symbol)
        if not item:
            continue
        delta = item.get("amount_change_pct")
        try:
            is_up = float(delta) > 0 if delta is not None else None
        except (TypeError, ValueError):
            is_up = None
        trend = "放量" if is_up else "缩量" if is_up is False else "量能持平"
        diff = abs(float(item.get("amount") or 0) - float(item.get("prev_amount") or 0))
        fragments.append(
            f"{label}成交额 <b>{fmt_amount(item.get('amount'))}</b>，"
            f"较上一交易日{trend} <b>{fmt_amount(diff)}</b>"
            f"（{pct(delta)}）"
        )
    market = data.get("market") or {}
    fragments.append(
        f"全市场上涨 <span class=\"up\">{int(market.get('up_count', 0))}</span> 家、"
        f"下跌 <span class=\"down\">{int(market.get('down_count', 0))}</span> 家，"
        f"涨跌幅中位数 <b class=\"{pct_class(market.get('median_pct'))}\">"
        f"{pct(market.get('median_pct'))}</b>"
    )
    return '<p class="comment">' + "；".join(fragments) + "。</p>"


def render_sector_section(data: dict[str, Any]) -> str:
    tables = data.get("sector_tables") or {}
    tabs = [
        ("amount", "成交额最大", tables.get("amount") or []),
        ("net", "净流入最多", tables.get("net") or []),
        ("heat", "热度最高", tables.get("heat") or []),
        ("limit", "涨停最多", tables.get("limit") or []),
    ]
    buttons: list[str] = []
    panes: list[str] = []
    for index, (key, label, rows) in enumerate(tabs):
        active = " active" if index == 0 else ""
        buttons.append(
            f'<button class="tab{active}" data-tab="{key}" type="button">'
            f'{label}<span class="tab-count">{len(rows)}</span></button>'
        )
        panes.append(
            f'<div class="pane{active}" data-pane="{key}">'
            f"{sector_table(rows, key)}</div>"
        )
    panels = (
        '<div class="subpanel">'
        '<div class="subpanel-head"><h3>行业板块排行</h3>'
        '<span class="hint">东财 EM2016 二级行业 · 样本 ≥ 3 只 · 点击列头标签切换</span></div>'
        f'<div class="tabs" data-tabs="sector-tabs">{"".join(buttons)}</div>'
        f'<div id="sector-tabs">{"".join(panes)}</div>'
        "</div>"
    )
    themes = data.get("themes") or []
    theme_panel = (
        '<div class="subpanel">'
        '<div class="subpanel-head"><h3>淘股吧题材热度</h3>'
        '<span class="hint">题材榜公开数据；展示人气龙头 / 中军 / 日内龙</span></div>'
        f"{theme_table(themes)}"
        "</div>"
    )
    method = (
        '<p class="method">口径说明：板块成交额、净流入为成分股求和；净流入取自个股主力净流入；'
        "热度按同花顺、东方财富、雪球热榜名次加权（第 1 名 50 分，逐名递减）并归一化到 0–100；"
        "涨停数为同花顺涨停池按板块聚合，连板为其中 2 板及以上个股。</p>"
    )
    return panels + theme_panel + method


def render_stock_section(data: dict[str, Any]) -> str:
    hot_lists = data.get("hot_lists") or {}
    buttons: list[str] = []
    panes: list[str] = []
    for index, key in enumerate(HOT_SOURCE_ORDER):
        rows = hot_lists.get(key) or []
        active = " active" if index == 0 else ""
        label = SOURCE_LABELS.get(key, key)
        buttons.append(
            f'<button class="tab{active}" data-tab="{key}" type="button">'
            f'{esc(label)}<span class="tab-count">{len(rows)}</span></button>'
        )
        note = ""
        if key == "em":
            note = '<p class="note">东方财富人气榜公开接口仅提供排名与名次变化，热度值为空。</p>'
        panes.append(
            f'<div class="pane{active}" data-pane="{key}">'
            f"{note}{hot_table(rows, key)}</div>"
        )
    hot_panel = (
        '<div class="subpanel">'
        '<div class="subpanel-head"><h3>各平台热度 Top 50</h3>'
        '<span class="hint">同花顺 / 东方财富 / 雪球</span></div>'
        f'<div class="tabs" data-tabs="hot-tabs">{"".join(buttons)}</div>'
        f'<div id="hot-tabs">{"".join(panes)}</div>'
        '<p class="note warn">通达信与淘股吧未公开个股热度榜，本期未接入，未以其他数据冒充。'
        "后续可接入本地通达信 / QMT 客户端补全。</p>"
        "</div>"
    )

    resonance = data.get("resonance") or []
    resonance_panel = (
        '<div class="subpanel">'
        '<div class="subpanel-head"><h3>跨平台共振个股</h3>'
        '<span class="hint">同一股票至少进入 2 个平台 Top 50，按上榜数与名次排序</span></div>'
        f"{resonance_table(resonance)}"
        "</div>"
    )

    top_tabs = [
        ("amount", "成交额 Top 100", data.get("top_amount") or []),
        ("turnover", "换手率 Top 100", data.get("top_turnover") or []),
        ("amplitude", "振幅 Top 100", data.get("top_amplitude") or []),
    ]
    buttons = []
    panes = []
    for index, (key, label, rows) in enumerate(top_tabs):
        active = " active" if index == 0 else ""
        buttons.append(
            f'<button class="tab{active}" data-tab="{key}" type="button">'
            f'{label}<span class="tab-count">{len(rows)}</span></button>'
        )
        panes.append(
            f'<div class="pane{active}" data-pane="{key}">{top_table(rows)}</div>'
        )
    top_panel = (
        '<div class="subpanel">'
        '<div class="subpanel-head"><h3>活跃个股榜单</h3>'
        '<span class="hint">成交额 / 换手率 / 振幅 Top 100 · 均含板块、涨停原因与几天几板</span></div>'
        f'<div class="tabs" data-tabs="top-tabs">{"".join(buttons)}</div>'
        f'<div id="top-tabs">{"".join(panes)}</div>'
        "</div>"
    )

    limit_ups = data.get("limit_ups") or []
    limit_panel = (
        '<div class="subpanel">'
        '<div class="subpanel-head"><h3>涨停个股全览</h3>'
        f'<span class="hint">同花顺涨停池 · 共 {len(limit_ups)} 只 · 按连板高度与首封时间排序</span></div>'
        f"{limit_table(limit_ups)}"
        "</div>"
    )
    return hot_panel + resonance_panel + top_panel + limit_panel


def render_sources(data: dict[str, Any]) -> str:
    sources = data.get("sources") or []
    if not sources:
        return empty_state("无数据源状态")
    rows: list[str] = []
    for item in sources:
        status = str(item.get("status") or "")
        status_label = {"ok": "正常", "warn": "降级", "off": "未接入"}.get(status, status)
        rows.append(
            "<tr>"
            f'<td class="l"><span class="source-dot {esc(status)}"></span>'
            f'{esc(item.get("name", ""))}</td>'
            f'<td class="l"><span class="status {esc(status)}">{esc(status_label)}</span></td>'
            f'<td class="l detail">{esc(item.get("detail", ""))}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="data-table source-table">'
        '<thead><tr><th class="l">数据源</th><th class="l">状态</th>'
        '<th class="l">说明</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div>"
    )


def render_warnings(data: dict[str, Any]) -> str:
    warnings = [str(item) for item in (data.get("warnings") or []) if item]
    if not warnings:
        return ""
    items = "".join(f"<li>{esc(item)}</li>" for item in warnings)
    return f'<div class="alert"><b>数据提示</b><ul>{items}</ul></div>'


# ---------------------------------------------------------------------------
# HTML document
# ---------------------------------------------------------------------------
CSS = """
:root{
  --bg:#070a11; --panel:#101624; --panel-2:#0c1220; --line:#1e2a3d;
  --line-soft:rgba(120,145,180,.14); --txt:#e8eef9; --muted:#8c9ab1;
  --dim:#5f6d84; --red:#ff4d5e; --green:#16c784; --gold:#f5b942;
  --blue:#5b8cff; --radius:16px;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{
  margin:0;color:var(--txt);line-height:1.55;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  background:
    radial-gradient(1200px 620px at 15% -8%,rgba(91,140,255,.14),transparent 62%),
    radial-gradient(1000px 520px at 92% -4%,rgba(245,185,66,.07),transparent 58%),
    var(--bg);
  -webkit-font-smoothing:antialiased;
}
a{color:inherit;text-decoration:none}
.topnav{
  position:sticky;top:0;z-index:80;border-bottom:1px solid var(--line);
  background:rgba(7,10,17,.82);backdrop-filter:blur(16px);
}
.nav-inner{max-width:1500px;margin:0 auto;padding:12px 24px;display:flex;align-items:center;gap:22px}
.brand{display:flex;align-items:center;gap:10px;font-weight:750;letter-spacing:.02em}
.brand-mark{
  width:28px;height:28px;border-radius:9px;display:grid;place-items:center;font-size:13px;
  background:linear-gradient(135deg,var(--red),#b4264f);box-shadow:0 6px 18px rgba(255,77,94,.28)
}
.nav-links{display:flex;gap:4px;margin-left:auto;flex-wrap:wrap}
.nav-links a{padding:7px 12px;border-radius:999px;color:var(--muted);font-size:13px}
.nav-links a:hover{background:rgba(91,140,255,.1);color:var(--txt)}
.wrap{max-width:1500px;margin:0 auto;padding:0 24px 70px}
.hero{padding:38px 0 24px}
.eyebrow{color:var(--gold);font-size:12px;letter-spacing:.18em;text-transform:uppercase;font-weight:700}
h1{font-size:clamp(28px,4vw,46px);line-height:1.12;margin:10px 0 8px;letter-spacing:-.02em}
.hero-sub{color:var(--muted);font-size:14px;margin:0}
.meta-row{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}
.pill{
  display:inline-flex;align-items:center;gap:7px;padding:7px 12px;border-radius:999px;
  border:1px solid var(--line);background:rgba(16,22,36,.72);color:var(--muted);font-size:12.5px
}
.pill b{color:var(--txt);font-weight:650}
.pill .dot{width:7px;height:7px;border-radius:50%;background:var(--green)}
.pill .dot.warn{background:var(--gold)}
.banner{
  margin:16px 0 0;padding:13px 16px;border-radius:12px;border:1px solid rgba(245,185,66,.28);
  background:rgba(245,185,66,.07);color:#e8c782;font-size:13.5px
}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:10px;margin:22px 0 8px}
.kpi{
  padding:14px 16px;border:1px solid var(--line);border-radius:14px;
  background:linear-gradient(180deg,rgba(18,26,43,.86),rgba(11,16,28,.86))
}
.kpi > span{display:block;color:var(--muted);font-size:12px;margin-bottom:4px}
.kpi b{font-size:21px;letter-spacing:-.01em;white-space:nowrap}
section{margin-top:40px;scroll-margin-top:80px}
.section-head{display:flex;align-items:flex-end;gap:14px;margin-bottom:16px;flex-wrap:wrap}
.section-no{
  width:38px;height:38px;border-radius:12px;display:grid;place-items:center;font-weight:800;
  background:linear-gradient(135deg,rgba(91,140,255,.2),rgba(91,140,255,.04));
  border:1px solid rgba(91,140,255,.3);color:#9cb6ff;font-size:14px
}
.section-head h2{margin:0;font-size:22px;letter-spacing:-.01em}
.section-head p{margin:0 0 2px;color:var(--muted);font-size:13px}
.subpanel{
  border:1px solid var(--line);border-radius:var(--radius);padding:18px;margin-top:14px;
  background:linear-gradient(180deg,rgba(18,26,43,.72),rgba(11,16,28,.86));
  box-shadow:0 18px 50px rgba(0,0,0,.18)
}
.subpanel-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:10px}
.subpanel-head h3{margin:0;font-size:15.5px}
.hint{color:var(--dim);font-size:12.5px}
.index-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.index-card{
  position:relative;overflow:hidden;border:1px solid var(--line);border-radius:18px;padding:18px;
  background:
    radial-gradient(420px 220px at 100% 0%,rgba(91,140,255,.10),transparent 60%),
    linear-gradient(180deg,#121a2b,#0b1120);
  box-shadow:0 20px 50px rgba(0,0,0,.2)
}
.index-head{display:flex;justify-content:space-between;align-items:center;gap:10px}
.idx-name{font-weight:700;font-size:15px}
.idx-code{color:var(--dim);font-size:11.5px}
.idx-main{display:flex;align-items:baseline;gap:12px;margin-top:10px}
.idx-price{font-size:32px;font-weight:750;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.idx-pct{font-size:15px;font-weight:700}
.idx-change{font-size:12.5px;margin-top:-2px;color:var(--muted)}
.spark{width:100%;height:64px;margin:10px 0 4px;display:block}
.spark-empty{height:64px;display:grid;place-items:center;color:var(--dim);font-size:12px}
.idx-stats{display:grid;grid-template-columns:1fr 1fr;gap:8px 14px;padding-top:10px;border-top:1px solid var(--line-soft)}
.idx-stats div{display:flex;justify-content:space-between;gap:8px;font-size:12px}
.idx-stats span{color:var(--muted)}
.idx-stats b{font-weight:600;text-align:right}
.comment{
  margin:14px 0 0;padding:14px 16px;border-radius:12px;border:1px solid var(--line);
  background:rgba(16,22,36,.6);color:var(--muted);font-size:13px;line-height:1.8
}
.comment b{color:var(--txt);font-weight:650}
.method{color:var(--dim);font-size:12px;line-height:1.8;margin:12px 2px 0}
.note{color:var(--muted);font-size:12.5px;margin:8px 2px 10px}
.note.warn{color:#d9b268}
.tabs{display:flex;gap:7px;flex-wrap:wrap;margin:12px 0}
.tab{
  display:inline-flex;align-items:center;gap:7px;padding:8px 14px;border-radius:999px;cursor:pointer;
  border:1px solid var(--line);background:#0c1322;color:var(--muted);font-size:12.5px;
  transition:all .16s ease;font-family:inherit
}
.tab:hover{color:var(--txt);border-color:rgba(91,140,255,.4)}
.tab.active{
  color:#fff;border-color:rgba(91,140,255,.55);
  background:linear-gradient(135deg,rgba(91,140,255,.32),rgba(91,140,255,.12));
  box-shadow:0 6px 20px rgba(91,140,255,.16)
}
.tab-count{
  font-size:10.5px;padding:1px 6px;border-radius:999px;background:rgba(255,255,255,.08);color:var(--muted)
}
.tab.active .tab-count{background:rgba(255,255,255,.16);color:#dfe8ff}
.pane{display:none}
.pane.active{display:block;animation:fade .18s ease}
@keyframes fade{from{opacity:.3;transform:translateY(3px)}to{opacity:1;transform:none}}
.table-wrap{
  overflow:auto;border:1px solid var(--line);border-radius:13px;max-height:720px;
  background:rgba(8,12,20,.42);scrollbar-width:thin;scrollbar-color:#2a3a55 transparent
}
.table-wrap.table-tall{max-height:900px}
.table-wrap::-webkit-scrollbar{width:9px;height:9px}
.table-wrap::-webkit-scrollbar-thumb{background:#26344c;border-radius:9px}
table{width:100%;border-collapse:collapse;font-size:12.5px;white-space:nowrap}
thead th{
  position:sticky;top:0;z-index:3;background:#131c2e;color:#9aaac2;font-weight:650;
  text-align:right;padding:10px 12px;border-bottom:1px solid var(--line)
}
thead th.l{text-align:left}
tbody td{padding:9px 12px;text-align:right;border-bottom:1px solid var(--line-soft);font-variant-numeric:tabular-nums}
tbody td.l{text-align:left}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:rgba(91,140,255,.06)}
tbody tr{transition:background .12s ease}
.up{color:var(--red)!important}
.down{color:var(--green)!important}
.flat{color:var(--muted)!important}
.muted{color:var(--dim)}
.code{color:#9fb0c8;font-size:11.5px;letter-spacing:.02em}
.name-cell{display:flex;flex-direction:column;line-height:1.25;gap:2px}
.name-cell b{font-weight:650;color:#eef3fb}
.name-cell small,.sector-table small{color:var(--dim);font-size:10.5px;font-weight:400}
.sector-table small{display:block}
.mini-flag{
  display:inline-block;margin-left:5px;padding:0 4px;border-radius:4px;
  background:rgba(22,199,132,.12);border:1px solid rgba(22,199,132,.22);
  color:var(--green);font-size:9.5px;font-weight:650;vertical-align:middle
}
.sector{color:#c4d2e8}
.sector-unknown{color:var(--dim)}
.rank{
  display:inline-grid;place-items:center;min-width:23px;height:23px;padding:0 6px;border-radius:7px;
  background:rgba(255,255,255,.045);color:#9aaac2;font-size:11.5px;font-weight:700
}
.rank-top{background:rgba(245,185,66,.14);color:var(--gold);border:1px solid rgba(245,185,66,.22)}
.rank-chg{display:block;font-size:10px;margin-top:2px;font-weight:600}
.tag{
  display:inline-flex;align-items:center;padding:2px 7px;border-radius:6px;margin:1px 4px 1px 0;
  background:rgba(91,140,255,.12);border:1px solid rgba(91,140,255,.2);color:#a9c0ff;font-size:10.8px
}
.tag.limit{background:rgba(255,77,94,.12);border-color:rgba(255,77,94,.3);color:#ff8a96;font-weight:650}
.tag.theme{background:rgba(245,185,66,.1);border-color:rgba(245,185,66,.22);color:#e6c273}
.tag.proxy{background:rgba(255,255,255,.05);border-color:var(--line);color:var(--muted)}
.limit-cell{display:inline-flex;flex-direction:column;gap:3px;align-items:flex-start;white-space:normal;max-width:240px}
.reason{color:var(--dim);font-size:10.8px;line-height:1.35}
.reason-cell{white-space:normal;min-width:210px;max-width:340px;color:#b9c6da;line-height:1.45}
.heat{display:flex;align-items:center;gap:8px;justify-content:flex-end}
.heat-bar{display:inline-block;width:52px;height:5px;border-radius:99px;background:rgba(255,255,255,.07);overflow:hidden}
.heat-bar i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#f5b942,#ff7a45)}
.heat-num{font-variant-numeric:tabular-nums;color:#e6c273;min-width:30px;text-align:right}
.hot-num{color:#e6c273;font-weight:650;margin-right:5px;font-variant-numeric:tabular-nums}
.meta-cell{white-space:normal;min-width:150px;max-width:280px}
.hot-names{max-width:200px;overflow:hidden;text-overflow:ellipsis;color:#9fb0c8}
.ranks{color:#a9c0ff;font-size:11.5px}
.res-count{
  display:inline-grid;place-items:center;width:24px;height:24px;border-radius:50%;
  background:rgba(245,185,66,.14);border:1px solid rgba(245,185,66,.28);color:var(--gold);font-weight:750
}
.focus{color:#dbe6f7}
.empty{
  display:flex;align-items:center;justify-content:center;gap:10px;min-height:120px;
  color:var(--dim);font-size:13px;border:1px dashed var(--line);border-radius:13px
}
.empty span{font-size:20px;opacity:.6}
.alert{
  margin-top:16px;padding:14px 16px;border-radius:12px;
  border:1px solid rgba(245,185,66,.25);background:rgba(245,185,66,.06);color:#d9c08a;font-size:12.5px
}
.alert b{color:#f0d49a}
.alert ul{margin:7px 0 0;padding-left:18px}
.alert li{margin:2px 0}
.status{display:inline-flex;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:650}
.status.ok{background:rgba(22,199,132,.12);color:var(--green)}
.status.warn{background:rgba(245,185,66,.12);color:var(--gold)}
.status.off{background:rgba(255,255,255,.05);color:var(--muted)}
.source-dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:8px;background:var(--dim)}
.source-dot.ok{background:var(--green);box-shadow:0 0 8px rgba(22,199,132,.5)}
.source-dot.warn{background:var(--gold)}
.source-dot.off{background:#45536a}
.source-table .detail{white-space:normal;color:var(--muted);min-width:320px}
.searchbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:4px 0 14px}
.searchbar label{color:var(--muted);font-size:12.5px}
.searchbar input{
  flex:1;min-width:230px;max-width:520px;padding:9px 13px;border-radius:10px;
  border:1px solid var(--line);background:#0a101c;color:var(--txt);font-size:13px;outline:none;font-family:inherit
}
.searchbar input:focus{border-color:rgba(91,140,255,.55);box-shadow:0 0 0 3px rgba(91,140,255,.1)}
.searchbar button{
  padding:9px 13px;border-radius:10px;border:1px solid var(--line);background:#0c1322;
  color:var(--muted);cursor:pointer;font-family:inherit;font-size:12.5px
}
.searchbar button:hover{color:var(--txt);border-color:rgba(91,140,255,.4)}
.search-hint{color:var(--gold);font-size:12px}
.footer{margin-top:44px;padding-top:20px;border-top:1px solid var(--line);color:var(--dim);font-size:11.5px;line-height:1.9}
.footer b{color:var(--muted)}
@media (max-width:760px){
  .wrap{padding:0 14px 50px}.nav-inner{padding:10px 14px}.nav-links{display:none}
  .hero{padding-top:26px}.idx-price{font-size:27px}
  .subpanel{padding:12px}.index-card{padding:14px}
  thead th,tbody td{padding:8px 9px}
}
@media print{
  body{background:#fff;color:#111}.topnav,.searchbar{display:none}
  .subpanel,.index-card,.kpi{box-shadow:none;background:#fff;border-color:#ddd}
  .pane{display:block!important}
}
"""


def render_html(data: dict[str, Any]) -> str:
    generated_at = esc(str(data.get("generated_at", "")).replace("T", " ")[:19])
    data_date = str(data.get("data_date") or "")
    generated_date = str(data.get("generated_date") or "")
    status = str(data.get("session_status") or "")
    weekday = weekday_cn(data_date)
    market = data.get("market") or {}
    indexes = data.get("indexes") or []
    limit_ups = data.get("limit_ups") or []

    data_date_label = f"{data_date} {weekday}" if weekday else data_date
    non_trading = ""

    total_delta = market.get("total_amount_change_pct")
    total_delta_text = delta_cell(total_delta)
    total_amount = fmt_amount(market.get("total_amount"))
    net_inflow = market.get("total_net_inflow")
    up_count = int(market.get("up_count", 0))
    down_count = int(market.get("down_count", 0))
    limit_count = int(market.get("limit_up_count") or len(limit_ups))
    limit_down = int(market.get("limit_down_count", 0))
    median_pct = market.get("median_pct")
    stock_count = int(market.get("stock_count", 0))

    if data_date and generated_date and data_date != generated_date:
        non_trading = (
            f'<div class="banner">今日（{esc(generated_date)} {weekday_cn(generated_date)}）'
            f"为非交易日，以下展示最近交易日 <b>{esc(data_date_label)}</b> 的收盘数据。</div>"
        )

    kpis = [
        ("两市成交额", total_amount, ""),
        ("较上一交易日", total_delta_text, ""),
        ("上涨 / 下跌", f'<span class="up">{up_count}</span> / <span class="down">{down_count}</span>', ""),
        ("涨停 / 跌停", f'<span class="up">{limit_count}</span> / <span class="down">{limit_down}</span>', ""),
        ("涨跌幅中位数", f'<span class="{pct_class(median_pct)}">{pct(median_pct)}</span>', ""),
        ("主力净流入", f'<span class="{pct_class(net_inflow)}">{fmt_amount_signed(net_inflow)}</span>', ""),
        ("统计个股", f"{stock_count:,}", ""),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><span>{label}</span><b>{value}</b></div>' for label, value, _ in kpis
    )

    sources = data.get("sources") or []
    ok_count = sum(1 for item in sources if item.get("status") == "ok")
    warn_count = sum(1 for item in sources if item.get("status") == "warn")
    source_dot_class = "dot" if warn_count == 0 else "dot warn"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>A股每日行情复盘 · {esc(data_date_label)}</title>
<style>{CSS}</style>
</head>
<body>
<nav class="topnav">
  <div class="nav-inner">
    <div class="brand"><span class="brand-mark">A</span><span>A股每日复盘</span></div>
    <div class="nav-links">
      <a href="#index">指数分析</a>
      <a href="#sector">板块分析</a>
      <a href="#stock">个股分析</a>
      <a href="#sources">数据源</a>
    </div>
  </div>
</nav>
<main class="wrap">
  <header class="hero">
    <div class="eyebrow">China A-Share Daily Brief</div>
    <h1>A股每日行情复盘</h1>
    <p class="hero-sub">指数 · 板块 · 个股三层拆解，数据来自公开行情接口，收盘后自动生成。</p>
    <div class="meta-row">
      <span class="pill"><span class="{source_dot_class}"></span>数据日期 <b>{esc(data_date_label)}</b></span>
      <span class="pill">生成时间 <b>{generated_at}</b></span>
      <span class="pill">状态 <b>{esc(status)}</b></span>
      <span class="pill">数据源 <b>{ok_count} 正常</b>{f' / {warn_count} 降级' if warn_count else ""}</span>
    </div>
    {non_trading}
    <div class="kpis">{kpi_html}</div>
  </header>

  <section id="index">
    <div class="section-head">
      <span class="section-no">01</span>
      <div><h2>指数分析</h2><p>上证指数 · 深证成指 · 科创50 · 与上一交易日对比</p></div>
    </div>
    {render_index_cards(indexes)}
    {index_comment(data)}
    <div class="subpanel">
      <div class="subpanel-head"><h3>指数明细对比</h3>
      <span class="hint">成交额与成交量均与上一交易日直接对比</span></div>
      {render_index_table(indexes)}
    </div>
  </section>

  <section id="sector">
    <div class="section-head">
      <span class="section-no">02</span>
      <div><h2>板块分析</h2><p>成交额最大 · 净流入最多 · 热度最高 · 涨停最多</p></div>
    </div>
    {render_sector_section(data)}
  </section>

  <section id="stock">
    <div class="section-head">
      <span class="section-no">03</span>
      <div><h2>个股分析</h2><p>跨平台热榜 Top 50 · 成交额 / 换手率 / 振幅 Top 100 · 涨停全览</p></div>
    </div>
    <div class="searchbar">
      <label for="stockSearch">全表搜索</label>
      <input id="stockSearch" type="search" placeholder="输入代码、名称或板块，如 600519 / 白酒 / 半导体"/>
      <button id="searchClear" type="button">清空</button>
      <span class="search-hint" id="searchHint"></span>
    </div>
    {render_stock_section(data)}
  </section>

  <section id="sources">
    <div class="section-head">
      <span class="section-no">04</span>
      <div><h2>数据源状态</h2><p>公开接口可用性与降级说明</p></div>
    </div>
    {render_warnings(data)}
    <div class="subpanel">{render_sources(data)}</div>
    <p class="method">
      口径说明：全市场快照来自雪球筛选器（沪深 + 北交所）；指数来自腾讯行情与雪球日 K；行业分类来自东方财富
      F10（EM2016）；涨停池与热榜来自同花顺；人气榜来自东方财富；热股榜来自雪球；题材榜来自淘股吧。
      热度为同花顺、东方财富、雪球三榜名次加权指标，不是官方热度值。通达信与淘股吧无公开个股热度接口，本期未接入。
    </p>
  </section>

  <footer class="footer">
    <b>免责声明：</b>本报告仅用于行情复盘与数据研究，不构成任何投资建议。公开接口可能存在延迟、缺失或口径差异，
    请以交易所及券商终端数据为准。涨停原因来自同花顺题材标注，仅供复盘参考。<br/>
    生成于 {generated_at} · 数据日期 {esc(data_date_label)} · 自动化任务输出
  </footer>
</main>
<script>
(function(){{
  document.querySelectorAll('[data-tabs]').forEach(function(group){{
    var targetId = group.getAttribute('data-tabs');
    var target = document.getElementById(targetId);
    group.querySelectorAll('[data-tab]').forEach(function(btn){{
      btn.addEventListener('click', function(){{
        group.querySelectorAll('[data-tab]').forEach(function(b){{ b.classList.toggle('active', b === btn); }});
        if(target){{
          target.querySelectorAll('[data-pane]').forEach(function(pane){{
            pane.classList.toggle('active', pane.getAttribute('data-pane') === btn.getAttribute('data-tab'));
          }});
        }}
      }});
    }});
  }});

  var input = document.getElementById('stockSearch');
  var hint = document.getElementById('searchHint');
  var rows = Array.prototype.slice.call(document.querySelectorAll('tbody tr[data-search]'));
  function applyFilter(){{
    if(!input) return;
    var query = (input.value || '').trim().toLowerCase();
    var visible = 0;
    rows.forEach(function(row){{
      var hit = !query || (row.getAttribute('data-search') || '').indexOf(query) !== -1;
      row.style.display = hit ? '' : 'none';
      if(hit) visible++;
    }});
    if(hint) hint.textContent = query ? ('匹配 ' + visible + ' 行') : '';
  }}
  if(input) input.addEventListener('input', applyFilter);
  var clear = document.getElementById('searchClear');
  if(clear){{
    clear.addEventListener('click', function(){{
      if(input){{ input.value = ''; applyFilter(); input.focus(); }}
    }});
  }}
}})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------
def md(value: Any) -> str:
    return str("" if value is None else value).replace("|", "\\|").replace("\n", " ").strip()


def md_stock_table(rows: list[dict[str, Any]], limit: int = 20) -> str:
    if not rows:
        return "> 本期暂无数据\n"
    lines = [
        "| # | 代码 | 名称 | 板块 | 涨跌幅 | 成交额 | 换手率 | 振幅 | 几天几板 | 涨停原因 |",
        "|---:|---|---|---|---:|---:|---:|---:|---|---|",
    ]
    for index, row in enumerate(rows[:limit], 1):
        limit_row = row.get("limit_up") if row.get("limit_up") else row if row.get("reason") else None
        lines.append(
            "| {rank} | {code} | {name} | {sector} | {pct} | {amount} | {turnover} | {amplitude} | {limit} | {reason} |".format(
                rank=index,
                code=md(row.get("code")),
                name=md(row.get("name")),
                sector=md(row.get("sector") or "未分类"),
                pct=pct(row.get("pct")),
                amount=fmt_amount(row.get("amount")),
                turnover=f'{num(row.get("turnover"), 2)}%',
                amplitude=f'{num(row.get("amplitude"), 2)}%',
                limit=md(board_text(limit_row)),
                reason=md((limit_row or {}).get("reason") or "—"),
            )
        )
    return "\n".join(lines) + "\n"


def md_sector_table(rows: list[dict[str, Any]], limit: int = 10) -> str:
    if not rows:
        return "> 板块聚合数据不足\n"
    lines = [
        "| # | 板块 | 平均涨跌 | 成交额 | 净流入 | 热度 | 涨停 | 领涨股 |",
        "|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for index, row in enumerate(rows[:limit], 1):
        lines.append(
            "| {rank} | {name} | {pct} | {amount} | {net} | {heat} | {limit} | {leader} |".format(
                rank=index,
                name=md(row.get("name")),
                pct=pct(row.get("avg_pct")),
                amount=fmt_amount(row.get("amount")),
                net=fmt_amount_signed(row.get("net_inflow")),
                heat=num(row.get("heat"), 1),
                limit=int(row.get("limit_count", 0)),
                leader=md(f'{row.get("leader", "")} {pct(row.get("leader_pct"))}'.strip()),
            )
        )
    return "\n".join(lines) + "\n"


def render_markdown(data: dict[str, Any]) -> str:
    data_date = str(data.get("data_date") or "")
    generated_at = data.get("generated_at", "")
    market = data.get("market") or {}
    indexes = data.get("indexes") or []
    hot_lists = data.get("hot_lists") or {}
    sector_tables = data.get("sector_tables") or {}
    limit_ups = data.get("limit_ups") or []
    themes = data.get("themes") or []

    lines: list[str] = []
    lines.append(f"# A股每日行情复盘 · {data_date} {weekday_cn(data_date)}")
    lines.append("")
    lines.append(
        f"> 生成时间：{generated_at} ｜ 状态：{data.get('session_status', '')} ｜ "
        f"数据源：{sum(1 for x in data.get('sources') or [] if x.get('status') == 'ok')} 正常 / "
        f"{sum(1 for x in data.get('sources') or [] if x.get('status') == 'warn')} 降级"
    )
    if data_date and data_date != data.get("generated_date"):
        lines.append(">")
        lines.append(f"> 今日为非交易日，以下为最近交易日 {data_date} 的收盘数据。")
    lines.append("")
    lines.append("## 市场概览")
    lines.append("")
    lines.append(
        f"- 两市成交额：**{fmt_amount(market.get('total_amount'))}**"
        f"（较上一交易日 {pct(market.get('total_amount_change_pct'))}）"
    )
    lines.append(
        f"- 涨跌家数：上涨 **{int(market.get('up_count', 0))}** / 下跌 "
        f"**{int(market.get('down_count', 0))}** / 平盘 {int(market.get('flat_count', 0))}，"
        f"中位数 {pct(market.get('median_pct'))}"
    )
    lines.append(
        f"- 涨停 **{int(market.get('limit_up_count', 0))}** 只，跌停 "
        f"**{int(market.get('limit_down_count', 0))}** 只；主力净流入 "
        f"**{fmt_amount_signed(market.get('total_net_inflow'))}**"
    )
    lines.append(f"- 统计个股：{int(market.get('stock_count', 0)):,} 只")
    lines.append("")

    lines.append("## 一、指数分析")
    lines.append("")
    lines.append("| 指数 | 收盘 | 涨跌幅 | 成交额 | 昨日成交额 | 成交额变化 | 成交量 | 昨日成交量 | 成交量变化 | 振幅 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for item in indexes:
        lines.append(
            "| {name} | {price} | {pct} | {amount} | {prev_amount} | {delta} | {vol} | {prev_vol} | {vol_delta} | {amp} |".format(
                name=md(item.get("name")),
                price=num(item.get("price"), 2),
                pct=pct(item.get("pct")),
                amount=fmt_amount(item.get("amount")),
                prev_amount=fmt_amount(item.get("prev_amount")),
                delta=pct(item.get("amount_change_pct")),
                vol=fmt_lots(item.get("volume_lots")),
                prev_vol=fmt_lots(item.get("prev_volume_lots")),
                vol_delta=pct(item.get("volume_change_pct")),
                amp=f'{num(item.get("amplitude"), 2)}%',
            )
        )
    lines.append("")

    lines.append("## 二、板块分析")
    lines.append("")
    lines.append("### 成交额最大 Top 10")
    lines.append("")
    lines.append(md_sector_table(sector_tables.get("amount") or []))
    lines.append("### 净流入最多 Top 10")
    lines.append("")
    lines.append(md_sector_table(sector_tables.get("net") or []))
    lines.append("### 热度最高 Top 10")
    lines.append("")
    lines.append(md_sector_table(sector_tables.get("heat") or []))
    lines.append("### 涨停最多 Top 10")
    lines.append("")
    lines.append(md_sector_table(sector_tables.get("limit") or []))
    lines.append("### 淘股吧题材热度 Top 15")
    lines.append("")
    if themes:
        lines.append("| # | 题材 | 热度 | 涨跌幅 | 涨停 | 涨/跌 | 人气龙头 |")
        lines.append("|---:|---|---:|---:|---:|---:|---|")
        for index, theme in enumerate(themes[:15], 1):
            human = theme.get("human") or {}
            lines.append(
                f"| {index} | {md(theme.get('name'))} | {num(theme.get('heat'), 0)} | "
                f"{pct(theme.get('pct'))} | {int(theme.get('limit_up', 0))} | "
                f"{int(theme.get('up', 0))}/{int(theme.get('down', 0))} | "
                f"{md(human.get('name') or '—')} |"
            )
    else:
        lines.append("> 本期暂无题材数据")
    lines.append("")

    lines.append("## 三、个股分析")
    lines.append("")
    lines.append("### 各平台热度 Top 50")
    lines.append("")
    for key in HOT_SOURCE_ORDER:
        rows = hot_lists.get(key) or []
        lines.append(f"#### {SOURCE_LABELS.get(key, key)}（{len(rows)} 只）")
        lines.append("")
        lines.append(md_stock_table(rows, 20))
        lines.append("")
    lines.append("> 通达信与淘股吧没有公开的个股热度接口，本期未接入。")
    lines.append("")

    lines.append("### 跨平台共振 Top 15")
    lines.append("")
    resonance = data.get("resonance") or []
    if resonance:
        lines.append("| # | 代码 | 名称 | 板块 | 来源数 | 各榜排名 | 涨跌幅 | 成交额 | 几天几板 | 涨停原因 |")
        lines.append("|---:|---|---|---|---:|---|---:|---:|---|---|")
        for index, row in enumerate(resonance[:15], 1):
            ranks = row.get("ranks") or {}
            rank_text = " / ".join(
                f"{SOURCE_LABELS.get(k, k)}#{v}" for k, v in sorted(ranks.items(), key=lambda item: item[1])
            )
            limit_row = row.get("limit_up") or {}
            lines.append(
                f"| {index} | {md(row.get('code'))} | {md(row.get('name'))} | "
                f"{md(row.get('sector') or '未分类')} | {int(row.get('source_count', 0))} | "
                f"{md(rank_text)} | {pct(row.get('pct'))} | {fmt_amount(row.get('amount'))} | "
                f"{md(board_text(limit_row))} | {md(limit_row.get('reason') or '—')} |"
            )
    else:
        lines.append("> 本期没有跨平台同时上榜的个股")
    lines.append("")

    lines.append("### 成交额 Top 100（摘要前 30）")
    lines.append("")
    lines.append(md_stock_table(data.get("top_amount") or [], 30))
    lines.append("### 换手率 Top 100（摘要前 30）")
    lines.append("")
    lines.append(md_stock_table(data.get("top_turnover") or [], 30))
    lines.append("### 振幅 Top 100（摘要前 30）")
    lines.append("")
    lines.append(md_stock_table(data.get("top_amplitude") or [], 30))

    lines.append("### 涨停个股全览")
    lines.append("")
    if limit_ups:
        lines.append("| # | 代码 | 名称 | 板块 | 几天几板 | 涨停原因 | 成交额 | 换手率 | 振幅 | 首封 |")
        lines.append("|---:|---|---|---|---|---|---:|---:|---:|---|")
        for index, row in enumerate(limit_ups, 1):
            lines.append(
                f"| {index} | {md(row.get('code'))} | {md(row.get('name'))} | "
                f"{md(row.get('sector') or '未分类')} | {md(board_text(row))} | "
                f"{md(row.get('reason') or '—')} | {fmt_amount(row.get('amount'))} | "
                f"{num(row.get('turnover'), 2)}% | {num(row.get('amplitude'), 2)}% | "
                f"{md(row.get('first_time') or '—')} |"
            )
    else:
        lines.append("> 本期涨停池无数据")
    lines.append("")

    lines.append("## 四、数据源状态")
    lines.append("")
    lines.append("| 数据源 | 状态 | 说明 |")
    lines.append("|---|---|---|")
    status_label = {"ok": "正常", "warn": "降级", "off": "未接入"}
    for item in data.get("sources") or []:
        lines.append(
            f"| {md(item.get('name'))} | {status_label.get(item.get('status'), md(item.get('status')))} | "
            f"{md(item.get('detail'))} |"
        )
    lines.append("")
    warnings = data.get("warnings") or []
    if warnings:
        lines.append("### 数据提示")
        lines.append("")
        for warning in warnings:
            lines.append(f"- {md(warning)}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "本报告仅用于行情复盘与数据研究，不构成任何投资建议。公开接口可能存在延迟、缺失或口径差异，"
        "请以交易所及券商终端数据为准。"
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------
def _slim(row: dict[str, Any], drop: tuple[str, ...] = ()) -> dict[str, Any]:
    skip = {"industry", *drop}
    result: dict[str, Any] = {}
    for key, value in row.items():
        if key in skip:
            continue
        if key == "limit_up" and isinstance(value, dict):
            result[key] = {
                field: value.get(field)
                for field in ("high_days", "board_count", "days", "reason", "first_time", "last_time")
            }
        else:
            result[key] = value
    return result


def snapshot_payload(data: dict[str, Any]) -> dict[str, Any]:
    indexes = []
    for item in data.get("indexes") or []:
        copy = _slim(item, ("bars",))
        indexes.append(copy)
    return {
        "generated_at": data.get("generated_at"),
        "generated_date": data.get("generated_date"),
        "data_date": data.get("data_date"),
        "is_today": data.get("is_today"),
        "session_status": data.get("session_status"),
        "indexes": indexes,
        "market": data.get("market"),
        "stock_count": len(data.get("stocks") or {}),
        "limit_ups": [_slim(row) for row in data.get("limit_ups") or []],
        "hot_lists": {
            key: [_slim(row) for row in rows]
            for key, rows in (data.get("hot_lists") or {}).items()
        },
        "themes": data.get("themes"),
        "sector_tables": data.get("sector_tables"),
        "resonance": data.get("resonance"),
        "top_amount": [_slim(row) for row in data.get("top_amount") or []],
        "top_turnover": [_slim(row) for row in data.get("top_turnover") or []],
        "top_amplitude": [_slim(row) for row in data.get("top_amplitude") or []],
        "sources": data.get("sources"),
        "warnings": data.get("warnings"),
    }


def dump_snapshot(data: dict[str, Any]) -> str:
    return json.dumps(snapshot_payload(data), ensure_ascii=False, separators=(",", ":"))
