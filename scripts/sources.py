"""A-share daily market data sources.

All public endpoints used here are free and require no account.  The module
normalises the different vendor payloads into one small set of dictionaries so
that the renderer does not need to know which upstream produced a value.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests

CN_TZ = ZoneInfo("Asia/Shanghai")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "data" / "cache"
SNAPSHOT_DIR = BASE_DIR / "data" / "snapshots"
REPORT_DIR = BASE_DIR / "reports"
for _d in (CACHE_DIR, SNAPSHOT_DIR, REPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Retry policy for critical upstream calls.
CRITICAL_RETRIES = 5
CRITICAL_BACKOFF = 2.0

INDEXES = [
    # xueqiu symbol, display name, tencent symbol, short label
    ("SH000001", "上证指数", "sh000001", "上证"),
    ("SZ399001", "深证成指", "sz399001", "深证"),
    ("SH000688", "科创50", "sh000688", "科创50"),
]


def now_cn() -> datetime:
    return datetime.now(CN_TZ)


def to_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if text in {"", "-", "--", "None", "null", "nan"}:
        return default
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def to_int(value: Any, default: int = 0) -> int:
    number = to_float(value)
    return default if number is None else int(number)


def clean_text(value: Any, limit: int | None = None) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        return text[: limit - 1] + "…"
    return text


class SourceLog:
    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def add(self, key: str, name: str, status: str, detail: str) -> None:
        self.items.append(
            {"key": key, "name": name, "status": status, "detail": clean_text(detail, 180)}
        )

    def as_list(self) -> list[dict[str, str]]:
        return self.items


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )
    return session


def request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: int = 25,
    retries: int = 3,
    backoff: float = 1.0,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=timeout,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001 - retry any network failure
            last_error = exc
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    assert last_error is not None
    raise last_error


def xueqiu_session() -> requests.Session:
    session = make_session()
    session.headers.update({"Referer": "https://xueqiu.com/"})
    request(
        session,
        "GET",
        "https://xueqiu.com/hq",
        timeout=20,
        retries=CRITICAL_RETRIES,
        backoff=CRITICAL_BACKOFF,
    )
    if "xq_a_token" not in session.cookies.get_dict():
        request(
            session,
            "GET",
            "https://xueqiu.com/",
            timeout=20,
            retries=CRITICAL_RETRIES,
            backoff=CRITICAL_BACKOFF,
        )
    return session


def xueqiu_json(session: requests.Session, url: str) -> dict[str, Any]:
    response = request(
        session,
        "GET",
        url,
        headers={"Referer": "https://xueqiu.com/"},
        timeout=30,
        retries=CRITICAL_RETRIES,
        backoff=CRITICAL_BACKOFF,
    )
    payload = response.json()
    if payload.get("error_code") == 400016:
        # Token expired: refresh the cookie jar once and retry.
        session.cookies.clear()
        request(
            session,
            "GET",
            "https://xueqiu.com/hq",
            timeout=20,
            retries=CRITICAL_RETRIES,
            backoff=CRITICAL_BACKOFF,
        )
        response = request(
            session,
            "GET",
            url,
            headers={"Referer": "https://xueqiu.com/"},
            timeout=30,
            retries=CRITICAL_RETRIES,
            backoff=CRITICAL_BACKOFF,
        )
        payload = response.json()
    return payload


def normalize_xq_stock(item: dict[str, Any]) -> dict[str, Any] | None:
    symbol = str(item.get("symbol") or "")
    if len(symbol) < 8 or not symbol[2:].isdigit():
        return None
    exchange, code = symbol[:2], symbol[2:]
    # The Xueqiu screener also returns B shares; this report covers A shares.
    if (exchange == "SH" and code.startswith("900")) or (
        exchange == "SZ" and code.startswith("200")
    ):
        return None
    return {
        "code": code,
        "symbol": symbol,
        "exchange": exchange,
        "name": clean_text(item.get("name")),
        "price": to_float(item.get("current"), 0.0) or 0.0,
        "pct": to_float(item.get("percent"), 0.0) or 0.0,
        "chg": to_float(item.get("chg"), 0.0) or 0.0,
        "amount": to_float(item.get("amount"), 0.0) or 0.0,
        "volume": to_float(item.get("volume"), 0.0) or 0.0,
        "turnover": to_float(item.get("turnover_rate"), 0.0) or 0.0,
        "amplitude": to_float(item.get("amplitude"), 0.0) or 0.0,
        "main_net_inflow": to_float(item.get("main_net_inflows"), 0.0) or 0.0,
        "limitup_days": to_int(item.get("limitup_days"), 0),
        "market_cap": to_float(item.get("market_capital"), 0.0) or 0.0,
        "float_market_cap": to_float(item.get("float_market_capital"), 0.0) or 0.0,
        "type": item.get("type"),
    }


def fetch_xq_screener(
    session: requests.Session,
    market_type: str = "sh_sz",
    max_pages: int = 60,
    log: Any = print,
    order: str = "desc",
) -> dict[str, dict[str, Any]]:
    """Fetch the whole market, sorted by turnover amount.

    Xueqiu caps both a page (100 rows) and a result set (5000 rows).  Walking
    the list once descending and once ascending unions the two 5000-row
    windows and covers the full active universe.
    """
    stocks: dict[str, dict[str, Any]] = {}
    total = None
    page = 1
    while page <= max_pages:
        url = (
            "https://stock.xueqiu.com/v5/stock/screener/quote/list.json"
            f"?page={page}&size=100&order={order}&orderby=amount&order_by=amount"
            f"&market=CN&type={market_type}"
        )
        try:
            payload = xueqiu_json(session, url)
        except Exception as exc:  # noqa: BLE001
            log(f"  xueqiu screener page {page} failed: {exc}")
            break
        data = payload.get("data") or {}
        total = to_int(data.get("count"), 0) or total
        items = data.get("list") or []
        if not items:
            break
        for item in items:
            normalized = normalize_xq_stock(item)
            if normalized:
                stocks[normalized["code"]] = normalized
        if page % 10 == 0:
            log(f"  xueqiu {market_type}: page {page}, {len(stocks)} stocks")
        if total and page * 100 >= total:
            break
        if len(items) < 100:
            break
        page += 1
        time.sleep(0.10)
    return stocks


def fetch_xq_top(
    session: requests.Session,
    order_by: str,
    size: int = 100,
) -> list[dict[str, Any]]:
    url = (
        "https://stock.xueqiu.com/v5/stock/screener/quote/list.json"
        f"?page=1&size={size}&order=desc&orderby={order_by}&order_by={order_by}"
        "&market=CN&type=sh_sz"
    )
    payload = xueqiu_json(session, url)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in (payload.get("data") or {}).get("list") or []:
        normalized = normalize_xq_stock(item)
        if not normalized or normalized["code"] in seen:
            continue
        seen.add(normalized["code"])
        rows.append(normalized)
    return rows


def fetch_tencent_quotes(symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
    symbols = list(symbols)
    url = "https://qt.gtimg.cn/q=" + ",".join(symbols)
    response = request(
        make_session(),
        "GET",
        url,
        headers={"Referer": "https://gu.qq.com/"},
        timeout=20,
    )
    response.encoding = "gbk"
    text = response.text
    quotes: dict[str, dict[str, Any]] = {}
    for symbol, raw in re.findall(r'v_([a-zA-Z0-9]+)="([^"]*)"', text):
        parts = raw.split("~")
        if len(parts) < 40:
            continue
        amount = None
        triplet = parts[35].split("/") if len(parts) > 35 else []
        if len(triplet) == 3:
            amount = to_float(triplet[2])
        if amount is None:
            amount_wan = to_float(parts[37] if len(parts) > 37 else None)
            amount = (amount_wan or 0.0) * 10000
        quotes[symbol] = {
            "symbol": symbol,
            "name": clean_text(parts[1]),
            "code": parts[2],
            "price": to_float(parts[3], 0.0) or 0.0,
            "prev_close": to_float(parts[4], 0.0) or 0.0,
            "open": to_float(parts[5], 0.0) or 0.0,
            "volume_lots": to_float(parts[6], 0.0) or 0.0,
            "timestamp": parts[30] if len(parts) > 30 else "",
            "change": to_float(parts[31], 0.0) or 0.0,
            "pct": to_float(parts[32], 0.0) or 0.0,
            "high": to_float(parts[33], 0.0) or 0.0,
            "low": to_float(parts[34], 0.0) or 0.0,
            "amount": amount or 0.0,
            "amplitude": to_float(parts[43], 0.0) or 0.0,
        }
    return quotes


def fetch_xq_kline(session: requests.Session, symbol: str, count: int = 5) -> list[dict[str, Any]]:
    begin = int(time.time() * 1000)
    url = (
        "https://stock.xueqiu.com/v5/stock/chart/kline.json"
        f"?symbol={symbol}&begin={begin}&period=day&type=before"
        f"&count=-{count}&indicator=kline"
    )
    payload = xueqiu_json(session, url)
    data = payload.get("data") or {}
    columns = data.get("column") or []
    bars: list[dict[str, Any]] = []
    for row in data.get("item") or []:
        record = dict(zip(columns, row))
        stamp = to_int(record.get("timestamp"), 0)
        if not stamp:
            continue
        day = datetime.fromtimestamp(stamp / 1000, CN_TZ).strftime("%Y-%m-%d")
        bars.append(
            {
                "date": day,
                "open": to_float(record.get("open"), 0.0) or 0.0,
                "high": to_float(record.get("high"), 0.0) or 0.0,
                "low": to_float(record.get("low"), 0.0) or 0.0,
                "close": to_float(record.get("close"), 0.0) or 0.0,
                "volume": to_float(record.get("volume"), 0.0) or 0.0,
                "amount": to_float(record.get("amount"), 0.0) or 0.0,
                "pct": to_float(record.get("percent"), 0.0) or 0.0,
            }
        )
    bars.sort(key=lambda bar: bar["date"])
    return bars


def fetch_tencent_kline(symbol: str, count: int = 5) -> list[dict[str, Any]]:
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={symbol},day,,,{count},qfq"
    )
    response = request(make_session(), "GET", url, timeout=25)
    payload = response.json()
    data = (payload.get("data") or {}).get(symbol) or {}
    rows = data.get("day") or data.get("qfqday") or []
    bars: list[dict[str, Any]] = []
    for row in rows:
        if len(row) < 6:
            continue
        bars.append(
            {
                "date": str(row[0]),
                "open": to_float(row[1], 0.0) or 0.0,
                "close": to_float(row[2], 0.0) or 0.0,
                "high": to_float(row[3], 0.0) or 0.0,
                "low": to_float(row[4], 0.0) or 0.0,
                "volume": (to_float(row[5], 0.0) or 0.0) * 100,  # lots -> shares
                "amount": 0.0,
                "pct": 0.0,
            }
        )
    bars.sort(key=lambda bar: bar["date"])
    return bars


def fetch_index_data(session: requests.Session) -> tuple[list[dict[str, Any]], str, list[str]]:
    warnings: list[str] = []
    quotes = fetch_tencent_quotes([item[2] for item in INDEXES])
    indexes: list[dict[str, Any]] = []
    data_date = ""
    for xq_symbol, name, tx_symbol, short_name in INDEXES:
        quote = quotes.get(tx_symbol) or {}
        try:
            bars = fetch_xq_kline(session, xq_symbol, count=5)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{name} 雪球K线失败：{exc}")
            try:
                bars = fetch_tencent_kline(tx_symbol, count=5)
            except Exception as exc2:  # noqa: BLE001
                warnings.append(f"{name} 腾讯K线失败：{exc2}")
                bars = []
        quote_stamp = str(quote.get("timestamp") or "")
        quote_date = ""
        if len(quote_stamp) >= 8 and quote_stamp[:8].isdigit():
            quote_date = f"{quote_stamp[:4]}-{quote_stamp[4:6]}-{quote_stamp[6:8]}"
        last_bar = bars[-1] if bars else None
        if quote_date and (not last_bar or last_bar["date"] <= quote_date):
            current_date = quote_date
        elif last_bar:
            current_date = last_bar["date"]
        else:
            current_date = now_cn().strftime("%Y-%m-%d")
        data_date = max(data_date, current_date)

        if last_bar and last_bar["date"] == current_date:
            today_bar = last_bar
            yesterday_bar = bars[-2] if len(bars) >= 2 else None
            amount = last_bar["amount"] or quote.get("amount", 0.0)
            volume_lots = last_bar["volume"] / 100 if last_bar["volume"] else quote.get("volume_lots", 0.0)
        else:
            today_bar = {
                "date": current_date,
                "open": quote.get("open", 0.0),
                "high": quote.get("high", 0.0),
                "low": quote.get("low", 0.0),
                "close": quote.get("price", 0.0),
                "volume": (quote.get("volume_lots", 0.0) or 0.0) * 100,
                "amount": quote.get("amount", 0.0),
                "pct": quote.get("pct", 0.0),
            }
            yesterday_bar = bars[-1] if bars else None
            amount = quote.get("amount", 0.0)
            volume_lots = quote.get("volume_lots", 0.0)
        prev_amount = yesterday_bar.get("amount", 0.0) if yesterday_bar else 0.0
        prev_volume_lots = (
            yesterday_bar.get("volume", 0.0) / 100 if yesterday_bar and yesterday_bar.get("volume") else 0.0
        )
        price = quote.get("price") or today_bar.get("close", 0.0)
        prev_close = quote.get("prev_close") or (yesterday_bar or {}).get("close", 0.0)
        pct = quote.get("pct")
        if pct is None:
            pct = today_bar.get("pct", 0.0)
        spark = [bar["close"] for bar in bars[-5:]]
        if spark and abs(spark[-1] - price) > 1e-9:
            spark.append(price)
        amount_change_pct = (
            (amount - prev_amount) / prev_amount * 100 if prev_amount else None
        )
        volume_change_pct = (
            (volume_lots - prev_volume_lots) / prev_volume_lots * 100
            if prev_volume_lots
            else None
        )
        indexes.append(
            {
                "symbol": xq_symbol,
                "name": name,
                "short_name": short_name,
                "code": quote.get("code", xq_symbol[2:]),
                "price": price,
                "prev_close": prev_close,
                "open": quote.get("open", today_bar.get("open", 0.0)),
                "high": quote.get("high", today_bar.get("high", 0.0)),
                "low": quote.get("low", today_bar.get("low", 0.0)),
                "change": quote.get("change", 0.0),
                "pct": pct or 0.0,
                "amount": amount,
                "prev_amount": prev_amount,
                "amount_change_pct": amount_change_pct,
                "volume_lots": volume_lots,
                "prev_volume_lots": prev_volume_lots,
                "volume_change_pct": volume_change_pct,
                "amplitude": quote.get("amplitude", 0.0),
                "spark": spark,
                "date": current_date,
                "quote_time": quote_stamp,
                "bars": bars,
            }
        )
    return indexes, data_date, warnings


def fetch_limit_up(trade_date: str) -> tuple[list[dict[str, Any]], str]:
    date_compact = trade_date.replace("-", "")
    url = (
        "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
        "?page=1&limit=200"
        "&field=199112,10,9001,330323,330324,330325,9002,330329,"
        "133971,133970,1968584,3475914,9003,9004"
        "&filter=HS,GEM2STAR&order_field=330324&order_type=0"
        f"&date={date_compact}"
    )
    response = request(
        make_session(),
        "GET",
        url,
        headers={"Referer": "https://data.10jqka.com.cn/"},
        timeout=25,
        retries=CRITICAL_RETRIES,
        backoff=CRITICAL_BACKOFF,
    )
    payload = response.json()
    data = payload.get("data") or {}
    pool = data.get("info") or []
    result: list[dict[str, Any]] = []
    for item in pool:
        high_days = clean_text(item.get("high_days"), 20)
        board_count, days = parse_high_days(high_days, item.get("high_days_value"))
        first_ts = to_int(item.get("first_limit_up_time"), 0)
        last_ts = to_int(item.get("last_limit_up_time"), 0)
        result.append(
            {
                "code": str(item.get("code") or ""),
                "name": clean_text(item.get("name")),
                "price": to_float(item.get("latest"), 0.0) or 0.0,
                "pct": to_float(item.get("change_rate"), 0.0) or 0.0,
                "turnover": to_float(item.get("turnover_rate"), 0.0) or 0.0,
                "reason": clean_text(item.get("reason_type"), 120),
                "high_days": high_days,
                "board_count": board_count,
                "days": days,
                "limit_up_type": clean_text(item.get("limit_up_type"), 20),
                "open_num": to_int(item.get("open_num"), 0),
                "order_amount": to_float(item.get("order_amount"), 0.0) or 0.0,
                "currency_value": to_float(item.get("currency_value"), 0.0) or 0.0,
                "is_again_limit": to_int(item.get("is_again_limit"), 0),
                "first_time": format_time(first_ts),
                "last_time": format_time(last_ts),
                "first_ts": first_ts,
            }
        )
    result.sort(key=lambda row: (-row["board_count"], -row["days"], row["first_ts"] or 10**12))
    return result, clean_text(data.get("page", {}).get("date") or date_compact)


def parse_high_days(high_days: str, high_days_value: Any = None) -> tuple[int, int]:
    text = clean_text(high_days)
    match = re.search(r"(\d+)\s*天\s*(\d+)\s*板", text)
    if match:
        return int(match.group(2)), int(match.group(1))
    match = re.search(r"(\d+)\s*连板", text)
    if match:
        return int(match.group(1)), int(match.group(1))
    if "首板" in text:
        return 1, 1
    if high_days_value:
        value = to_int(high_days_value, 0)
        # THS uses a bit mask. 240 -> 0b11110000 (4 consecutive boards).
        if value:
            boards = 0
            for shift in range(16):
                if value & (1 << shift):
                    boards += 1
            return max(boards, 1), max(boards, 1)
    return 1, 1


def format_time(timestamp: int) -> str:
    if not timestamp:
        return "—"
    try:
        return datetime.fromtimestamp(timestamp, CN_TZ).strftime("%H:%M")
    except (OverflowError, OSError, ValueError):
        return "—"


def fetch_ths_hot() -> list[dict[str, Any]]:
    url = (
        "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock"
        "?stock_type=a&type=day&list_type=normal"
    )
    response = request(
        make_session(),
        "GET",
        url,
        headers={"Referer": "https://www.10jqka.com.cn/"},
        timeout=25,
        retries=CRITICAL_RETRIES,
        backoff=CRITICAL_BACKOFF,
    )
    payload = response.json()
    rows = (payload.get("data") or {}).get("stock_list") or []
    result: list[dict[str, Any]] = []
    for item in rows[:50]:
        tag = item.get("tag") or {}
        concept_tag = tag.get("concept_tag") or []
        result.append(
            {
                "source": "ths",
                "source_name": "同花顺",
                "code": str(item.get("code") or ""),
                "name": clean_text(item.get("name")),
                "rank": to_int(item.get("order"), len(result) + 1),
                "rank_change": to_int(item.get("hot_rank_chg"), 0),
                "heat": to_float(item.get("rate"), 0.0) or 0.0,
                "pct": to_float(item.get("rise_and_fall"), 0.0) or 0.0,
                "concept_tags": [clean_text(x, 20) for x in concept_tag[:4] if x],
                "popularity_tag": clean_text(tag.get("popularity_tag"), 20),
                "analyse": clean_text(item.get("analyse"), 280),
                "analyse_title": clean_text(item.get("analyse_title"), 60),
            }
        )
    return result


def fetch_em_hot() -> list[dict[str, Any]]:
    url = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
    body = {
        "appId": "appId01",
        "globalId": "786e4c21-70dc-435a-93bb-38",
        "marketType": "",
        "pageNo": 1,
        "pageSize": 100,
    }
    response = request(
        make_session(),
        "POST",
        url,
        json_body=body,
        headers={"Referer": "https://guba.eastmoney.com/rank/"},
        timeout=25,
    )
    payload = response.json()
    rows = payload.get("data") or []
    result: list[dict[str, Any]] = []
    for item in rows[:50]:
        symbol = str(item.get("sc") or "")
        exchange = symbol[:2].upper()
        if len(symbol) < 8 or exchange not in {"SH", "SZ", "BJ"}:
            continue
        result.append(
            {
                "source": "em",
                "source_name": "东方财富",
                "code": symbol[2:],
                "exchange": exchange,
                "name": "",
                "rank": to_int(item.get("rk"), len(result) + 1),
                "rank_change": to_int(item.get("hisRc"), 0),
                "heat": None,
                "pct": None,
            }
        )
    return result


def fetch_xq_hot(session: requests.Session) -> list[dict[str, Any]]:
    url = (
        "https://stock.xueqiu.com/v5/stock/hot_stock/list.json"
        "?size=100&_type=10&type=10"
    )
    payload = xueqiu_json(session, url)
    rows = (payload.get("data") or {}).get("items") or []
    result: list[dict[str, Any]] = []
    for item in rows:
        symbol = str(item.get("symbol") or "").upper()
        exchange = str(item.get("exchange") or "").upper()
        code = re.sub(r"^(SH|SZ|BJ)", "", symbol)
        if exchange not in {"SH", "SZ", "BJ"} or not code.isdigit():
            continue
        result.append(
            {
                "source": "xq",
                "source_name": "雪球",
                "code": code,
                "symbol": symbol,
                "exchange": exchange,
                "name": clean_text(item.get("name")),
                "rank": len(result) + 1,
                "rank_change": to_int(item.get("rank_change"), 0),
                "heat": to_float(item.get("value"), 0.0) or 0.0,
                "pct": to_float(item.get("percent"), 0.0) or 0.0,
                "price": to_float(item.get("current"), 0.0) or 0.0,
            }
        )
        if len(result) >= 50:
            break
    return result


def fetch_taoguba_themes() -> list[dict[str, Any]]:
    url = "https://www.tgb.cn/ticai/getTiCaiList?_=" + str(int(time.time() * 1000))
    response = request(
        make_session(),
        "GET",
        url,
        headers={
            "Referer": "https://www.tgb.cn/ticai/ranking",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=25,
    )
    payload = response.json()
    rows = ((payload.get("dto") or {}).get("list")) or []
    themes: list[dict[str, Any]] = []
    for item in rows:
        messages = item.get("listMsg") or []
        message = messages[0] if messages else {}
        human = message.get("humanDragon") or {}
        mid = message.get("middleTroops") or {}
        day = message.get("dayDragon") or {}
        theme = {
            "seq": to_int(item.get("materialSeq"), 0),
            "name": clean_text(item.get("materialName")),
            "rank": to_int(item.get("sort"), len(themes) + 1),
            "heat": to_float(message.get("popularValue"), 0.0) or 0.0,
            "pct": to_float(message.get("materialRate"), 0.0) or 0.0,
            "limit_up": to_int(item.get("limitUpStocks"), 0),
            "up": to_int(item.get("upNum"), 0),
            "down": to_int(item.get("downNum"), 0),
            "ratio": to_float(item.get("materialAmountRatio"), 0.0) or 0.0,
            "hot_flag": clean_text(item.get("hotFlag"), 10),
            "human": normalize_tgb_stock(human, "人气龙头"),
            "mid": normalize_tgb_stock(mid, "中军"),
            "day": normalize_tgb_stock(day, "日内龙"),
        }
        themes.append(theme)
    themes.sort(key=lambda row: (row["rank"] or 10**6, -row["heat"]))
    return themes[:60]


def normalize_tgb_stock(item: dict[str, Any], role: str) -> dict[str, Any] | None:
    full_code = str(item.get("fullCode") or "")
    if not full_code:
        return None
    exchange = "BJ" if full_code.lower().startswith("bj") else full_code[:2].upper()
    code = re.sub(r"^(sh|sz|bj)", "", full_code.lower())
    if not code.isdigit():
        return None
    return {
        "code": code,
        "exchange": exchange,
        "name": clean_text(item.get("stockName")),
        "label": clean_text(item.get("label"), 20),
        "role": role,
    }


def fetch_industry_map() -> tuple[dict[str, dict[str, Any]], str, str]:
    """Return code -> industry metadata, a status string and a detail message."""
    cache_file = CACHE_DIR / "industry_map.json"
    rows: list[dict[str, Any]] = []
    pages = 1
    error = ""
    base = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    session = make_session()
    for page in range(1, 8):
        params = {
            "reportName": "RPT_F10_BASIC_ORGINFO",
            "columns": "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,SECURITY_TYPE,EM2016,INDUSTRYCSRC1",
            "pageNumber": page,
            "pageSize": 5000,
            "source": "WEB",
            "client": "WEB",
        }
        try:
            response = request(
                session,
                "GET",
                base,
                headers={"Referer": "https://data.eastmoney.com/"},
                params=params,
                timeout=40,
                retries=CRITICAL_RETRIES,
                backoff=CRITICAL_BACKOFF,
            )
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            break
        result = payload.get("result") or {}
        data = result.get("data") or []
        pages = to_int(result.get("pages"), pages) or pages
        if not data:
            break
        rows.extend(data)
        if page >= pages:
            break
        time.sleep(0.8)

    mapping: dict[str, dict[str, Any]] = {}
    for row in rows:
        secucode = str(row.get("SECUCODE") or "")
        security_type = str(row.get("SECURITY_TYPE") or "")
        if not secucode.endswith((".SH", ".SZ", ".BJ")):
            continue
        if "A股" not in security_type:
            continue
        code = str(row.get("SECURITY_CODE") or "")
        if not code:
            continue
        em2016 = clean_text(row.get("EM2016"))
        l1, sector, sub_sector = split_industry(em2016)
        entry = {
            "code": code,
            "name": clean_text(row.get("SECURITY_NAME_ABBR")),
            "security_type": security_type,
            "em2016": em2016,
            "l1": l1,
            "sector": sector,
            "sub_sector": sub_sector,
            "csrc": clean_text(row.get("INDUSTRYCSRC1")),
        }
        previous = mapping.get(code)
        if previous is None or (entry["em2016"] and not previous.get("em2016")):
            mapping[code] = entry

    if len(mapping) >= 3000:
        cache_file.write_text(
            json.dumps(
                {"updated_at": now_cn().isoformat(timespec="seconds"), "data": mapping},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return mapping, "ok", f"覆盖 {len(mapping):,} 条 A 股行业记录"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            cached_map = cached.get("data") or {}
            if cached_map:
                updated = cached.get("updated_at", "未知")
                detail = f"使用本地缓存（{updated}，{len(cached_map):,} 条）"
                if error:
                    detail += f"；在线更新失败：{error}"
                return cached_map, "warn", detail
        except Exception:  # noqa: BLE001
            pass
    detail = f"仅取得 {len(mapping):,} 条行业记录"
    if error:
        detail += f"；错误：{error}"
    return mapping, "warn", detail


def split_industry(em2016: str) -> tuple[str, str, str]:
    text = clean_text(em2016)
    if not text or text in {"-", "—"}:
        return "未分类", "未分类", "未分类"
    parts = [part.strip() for part in re.split(r"[-—/]", text) if part.strip()]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[-1]
    if len(parts) == 2:
        return parts[0], parts[1], parts[1]
    return parts[0], parts[0], parts[0]


def collect_all(log: Any = print) -> dict[str, Any]:
    generated_at = now_cn()
    sources = SourceLog()
    warnings: list[str] = []

    log("[1/7] 雪球会话与指数...")
    session = xueqiu_session()
    indexes, data_date, index_warnings = fetch_index_data(session)
    warnings.extend(index_warnings)
    if not data_date:
        data_date = generated_at.strftime("%Y-%m-%d")
    sources.add(
        "index",
        "指数行情",
        "ok" if indexes else "warn",
        f"{len(indexes)} 个指数，数据日 {data_date}",
    )

    log("[2/7] 全市场行情快照...")
    stocks: dict[str, dict[str, Any]] = {}
    snapshot_ok = 0
    for order, label in (("desc", "降序"), ("asc", "升序")):
        try:
            part = fetch_xq_screener(session, "sh_sz", max_pages=60, log=log, order=order)
            stocks.update(part)
            snapshot_ok += 1
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"全市场行情{label}遍历失败：{exc}")
    sh_sz_count = sum(1 for s in stocks.values() if s.get("exchange") in {"SH", "SZ"})
    if snapshot_ok:
        sources.add(
            "xq",
            "雪球行情",
            "ok" if snapshot_ok == 2 else "warn",
            f"沪深 A 股 {sh_sz_count:,} 只"
            + ("" if snapshot_ok == 2 else "（仅完成单向遍历，可能不完整）"),
        )
    else:
        sources.add("xq", "雪球行情", "warn", "全市场行情获取失败")
    bj_count = 0
    try:
        bj_stocks = fetch_xq_screener(session, "bj", max_pages=6, log=log)
        bj_count = len(bj_stocks)
        stocks.update(bj_stocks)
        if bj_count:
            sources.add("xq_bj", "北交所行情", "ok", f"{bj_count:,} 只")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"北交所行情失败：{exc}")
        sources.add("xq_bj", "北交所行情", "warn", f"失败：{exc}")

    log("[3/7] 换手率 / 振幅榜单...")
    top_turnover: list[dict[str, Any]] = []
    top_amplitude: list[dict[str, Any]] = []
    for key, order_by, target in (
        ("turnover", "turnover_rate", top_turnover),
        ("amplitude", "amplitude", top_amplitude),
    ):
        try:
            target.extend(fetch_xq_top(session, order_by, size=100))
            sources.add(key, "换手率榜" if key == "turnover" else "振幅榜", "ok", "Top 100")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{key} 榜失败：{exc}")
            sources.add(key, "换手率榜" if key == "turnover" else "振幅榜", "warn", f"失败：{exc}")

    log("[4/7] 行业分类...")
    industry_map, ind_status, ind_detail = fetch_industry_map()
    sources.add("industry", "东财行业分类", ind_status, ind_detail)
    if ind_status != "ok":
        warnings.append(f"行业分类降级：{ind_detail}")

    log("[5/7] 涨停池...")
    limit_ups: list[dict[str, Any]] = []
    try:
        limit_ups, _limit_date = fetch_limit_up(data_date)
        sources.add("limit_up", "同花顺涨停池", "ok", f"{len(limit_ups)} 只，数据日 {data_date}")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"涨停池失败：{exc}")
        sources.add("limit_up", "同花顺涨停池", "warn", f"失败：{exc}")

    log("[6/7] 跨平台热榜...")
    ths_hot: list[dict[str, Any]] = []
    em_hot: list[dict[str, Any]] = []
    xq_hot: list[dict[str, Any]] = []
    try:
        ths_hot = fetch_ths_hot()
        sources.add("ths_hot", "同花顺热股榜", "ok", f"{len(ths_hot)} 只")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"同花顺热榜失败：{exc}")
        sources.add("ths_hot", "同花顺热股榜", "warn", f"失败：{exc}")
    try:
        em_hot = fetch_em_hot()
        sources.add("em_hot", "东方财富人气榜", "ok", f"{len(em_hot)} 只")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"东财人气榜失败：{exc}")
        sources.add("em_hot", "东方财富人气榜", "warn", f"失败：{exc}")
    try:
        xq_hot = fetch_xq_hot(session)
        sources.add("xq_hot", "雪球热股榜", "ok", f"{len(xq_hot)} 只 A 股")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"雪球热股榜失败：{exc}")
        sources.add("xq_hot", "雪球热股榜", "warn", f"失败：{exc}")

    log("[7/7] 淘股吧题材榜...")
    themes: list[dict[str, Any]] = []
    try:
        themes = fetch_taoguba_themes()
        sources.add(
            "tgb",
            "淘股吧题材榜",
            "ok",
            f"{len(themes)} 个题材",
        )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"淘股吧题材榜失败：{exc}")
        sources.add("tgb", "淘股吧题材榜", "warn", f"失败：{exc}")

    sources.add(
        "tdx",
        "通达信热榜",
        "off",
        "无公开个股热度接口，本期未接入；可在后续接入本地通达信/QMT",
    )

    # ---- Normalise / enrich ------------------------------------------------
    for stock in stocks.values():
        industry = industry_map.get(stock["code"]) or {}
        stock["industry"] = industry
        stock["sector"] = industry.get("sector") or "未分类"
        stock["sub_sector"] = industry.get("sub_sector") or "未分类"
        stock["l1"] = industry.get("l1") or "未分类"

    limit_by_code = {row["code"]: row for row in limit_ups}
    for stock in stocks.values():
        stock["limit_up"] = limit_by_code.get(stock["code"])

    def enrich_hot(entry: dict[str, Any]) -> dict[str, Any]:
        code = entry.get("code", "")
        base = dict(stocks.get(code) or {})
        merged = {**base, **{k: v for k, v in entry.items() if v is not None}}
        merged.setdefault("code", code)
        merged.setdefault("name", entry.get("name") or code)
        merged.setdefault("exchange", entry.get("exchange") or "")
        industry = industry_map.get(code) or base.get("industry") or {}
        merged["industry"] = industry
        merged["sector"] = industry.get("sector") or base.get("sector") or "未分类"
        merged["sub_sector"] = industry.get("sub_sector") or base.get("sub_sector") or "未分类"
        merged["limit_up"] = limit_by_code.get(code)
        if not merged.get("amount"):
            merged["amount"] = base.get("amount", 0.0)
        if merged.get("pct") is None:
            merged["pct"] = base.get("pct", 0.0)
        return merged

    hot_lists = {
        "ths": [enrich_hot(x) for x in ths_hot],
        "em": [enrich_hot(x) for x in em_hot],
        "xq": [enrich_hot(x) for x in xq_hot],
    }

    # Text enrichment for Eastmoney hot entries: names/pct come from snapshot.
    for row in hot_lists["em"]:
        if not row.get("name") or row.get("name") == row.get("code"):
            base = stocks.get(row["code"]) or {}
            row["name"] = base.get("name") or row["code"]

    # ---- Top lists ---------------------------------------------------------
    def eligible(stock: dict[str, Any]) -> bool:
        return bool(stock.get("amount")) and stock.get("price", 0) > 0

    top_amount = sorted(
        (s for s in stocks.values() if eligible(s)),
        key=lambda s: s.get("amount", 0),
        reverse=True,
    )[:100]
    if not top_turnover:
        top_turnover = sorted(
            (s for s in stocks.values() if eligible(s)),
            key=lambda s: s.get("turnover", 0),
            reverse=True,
        )[:100]
    if not top_amplitude:
        top_amplitude = sorted(
            (s for s in stocks.values() if eligible(s)),
            key=lambda s: s.get("amplitude", 0),
            reverse=True,
        )[:100]
    # Ensure top lists carry the same enrichment as the snapshot.
    for row in top_amount + top_turnover + top_amplitude:
        industry = row.get("industry") or industry_map.get(row["code"]) or {}
        row["industry"] = industry
        row["sector"] = industry.get("sector") or row.get("sector") or "未分类"
        row["sub_sector"] = industry.get("sub_sector") or row.get("sub_sector") or "未分类"
        row["limit_up"] = limit_by_code.get(row["code"])

    # Limit-up rows missing from the snapshot get a minimal quote record.
    for limit in limit_ups:
        stock = stocks.get(limit["code"])
        if stock:
            limit.update(
                {
                    "amount": stock.get("amount", 0.0),
                    "amplitude": stock.get("amplitude", 0.0),
                    "turnover": stock.get("turnover", limit.get("turnover", 0.0)),
                    "sector": stock.get("sector", "未分类"),
                    "sub_sector": stock.get("sub_sector", "未分类"),
                    "exchange": stock.get("exchange", ""),
                }
            )
        else:
            industry = industry_map.get(limit["code"]) or {}
            limit.update(
                {
                    "amount": 0.0,
                    "amplitude": 0.0,
                    "sector": industry.get("sector", "未分类"),
                    "sub_sector": industry.get("sub_sector", "未分类"),
                    "exchange": limit["code"][:2],
                }
            )

    # ---- Sector aggregation ------------------------------------------------
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for stock in stocks.values():
        if stock.get("amount", 0) > 0 and stock.get("sector") not in {"", "未分类"}:
            groups[stock["sector"]].append(stock)

    heat_by_sector: dict[str, float] = defaultdict(float)
    hot_codes_by_sector: dict[str, set[str]] = defaultdict(set)
    hot_names_by_sector: dict[str, list[tuple[int, str]]] = defaultdict(list)
    source_heat: dict[str, dict[str, float]] = defaultdict(dict)
    for source_key, rows in hot_lists.items():
        for index, row in enumerate(rows[:50], 1):
            sector = row.get("sector") or "未分类"
            if sector == "未分类":
                continue
            weight = max(51 - index, 1)
            heat_by_sector[sector] += weight
            hot_codes_by_sector[sector].add(row["code"])
            hot_names_by_sector[sector].append((index, row.get("name") or row["code"]))
            source_heat[sector][source_key] = source_heat[sector].get(source_key, 0) + weight

    max_heat = max(heat_by_sector.values()) if heat_by_sector else 1
    limit_by_sector: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for limit in limit_ups:
        limit_by_sector[limit.get("sector") or "未分类"].append(limit)

    sectors: list[dict[str, Any]] = []
    for sector, members in groups.items():
        if len(members) < 3:
            continue
        amount = sum(m.get("amount", 0.0) for m in members)
        net = sum(m.get("main_net_inflow", 0.0) for m in members)
        avg_pct = sum(m.get("pct", 0.0) for m in members) / len(members)
        up_count = sum(1 for m in members if m.get("pct", 0) > 0)
        down_count = sum(1 for m in members if m.get("pct", 0) < 0)
        flat_count = len(members) - up_count - down_count
        leader = max(members, key=lambda m: m.get("pct", -999))
        heat = heat_by_sector.get(sector, 0.0)
        hot_names: list[str] = []
        for _, name in sorted(hot_names_by_sector.get(sector, [])):
            if name and name not in hot_names:
                hot_names.append(name)
            if len(hot_names) >= 3:
                break
        sector_limits = limit_by_sector.get(sector, [])
        board_count = sum(1 for row in sector_limits if row.get("board_count", 1) >= 2)
        sectors.append(
            {
                "name": sector,
                "stock_count": len(members),
                "amount": amount,
                "net_inflow": net,
                "avg_pct": avg_pct,
                "up_count": up_count,
                "down_count": down_count,
                "flat_count": flat_count,
                "leader": leader.get("name", ""),
                "leader_code": leader.get("code", ""),
                "leader_pct": leader.get("pct", 0.0),
                "heat_raw": heat,
                "heat": round(heat / max_heat * 100, 1) if max_heat else 0.0,
                "hot_count": len(hot_codes_by_sector.get(sector, set())),
                "hot_names": hot_names,
                "limit_count": len(sector_limits),
                "board_count": board_count,
                "limit_names": [row.get("name", "") for row in sector_limits[:4]],
                "source_heat": {
                    key: round(value / max_heat * 100, 1)
                    for key, value in source_heat.get(sector, {}).items()
                },
            }
        )

    sector_tables = {
        "amount": sorted(sectors, key=lambda row: row["amount"], reverse=True)[:30],
        "net": sorted(sectors, key=lambda row: row["net_inflow"], reverse=True)[:30],
        "heat": sorted(
            sectors,
            key=lambda row: (row["heat"], row["hot_count"], row["amount"]),
            reverse=True,
        )[:30],
        "limit": sorted(
            sectors,
            key=lambda row: (row["limit_count"], row["board_count"], row["amount"]),
            reverse=True,
        )[:30],
    }

    # ---- Cross-platform resonance -----------------------------------------
    resonance_map: dict[str, dict[str, Any]] = {}
    for source_key, rows in hot_lists.items():
        for index, row in enumerate(rows[:50], 1):
            code = row["code"]
            target = resonance_map.setdefault(
                code,
                {"code": code, "stock": row, "ranks": {}},
            )
            target["ranks"][source_key] = index
    resonance = []
    for code, entry in resonance_map.items():
        if len(entry["ranks"]) < 2:
            continue
        stock = entry["stock"]
        resonance.append(
            {
                "code": code,
                "name": stock.get("name") or code,
                "sector": stock.get("sector") or "未分类",
                "sub_sector": stock.get("sub_sector") or "未分类",
                "ranks": entry["ranks"],
                "source_count": len(entry["ranks"]),
                "best_rank": min(entry["ranks"].values()),
                "rank_sum": sum(entry["ranks"].values()),
                "amount": stock.get("amount", 0.0),
                "pct": stock.get("pct", 0.0),
                "limit_up": stock.get("limit_up"),
                "price": stock.get("price", 0.0),
            }
        )
    resonance.sort(key=lambda row: (-row["source_count"], row["rank_sum"]))
    resonance = resonance[:30]

    # ---- Market summary ----------------------------------------------------
    sh_index = next((x for x in indexes if x["symbol"] == "SH000001"), None)
    sz_index = next((x for x in indexes if x["symbol"] == "SZ399001"), None)
    total_amount = (sh_index or {}).get("amount", 0.0) + (sz_index or {}).get("amount", 0.0)
    prev_total_amount = (sh_index or {}).get("prev_amount", 0.0) + (sz_index or {}).get("prev_amount", 0.0)
    pct_values = sorted(s.get("pct", 0.0) for s in stocks.values() if s.get("amount", 0) > 0)
    median_pct = pct_values[len(pct_values) // 2] if pct_values else 0.0
    market = {
        "total_amount": total_amount,
        "prev_total_amount": prev_total_amount,
        "total_amount_change_pct": (
            (total_amount - prev_total_amount) / prev_total_amount * 100
            if prev_total_amount
            else None
        ),
        "total_net_inflow": sum(s.get("main_net_inflow", 0.0) for s in stocks.values()),
        "up_count": sum(1 for s in stocks.values() if s.get("pct", 0) > 0 and s.get("amount", 0) > 0),
        "down_count": sum(1 for s in stocks.values() if s.get("pct", 0) < 0 and s.get("amount", 0) > 0),
        "flat_count": sum(1 for s in stocks.values() if s.get("pct", 0) == 0 and s.get("amount", 0) > 0),
        "limit_up_count": len(limit_ups),
        "limit_down_count": sum(1 for s in stocks.values() if s.get("pct", 0) <= -9.8),
        "median_pct": median_pct,
        "stock_count": len(stocks),
        "sh_sz_count": len(stocks) - bj_count,
        "bj_count": bj_count,
    }

    # Add a bit of context to the status panel.
    if index_warnings:
        for warning in index_warnings:
            warnings.append(warning)
    if stocks and len(stocks) < 4000:
        warnings.append(f"行情快照仅 {len(stocks)} 只，可能不完整")

    return {
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "generated_date": generated_at.strftime("%Y-%m-%d"),
        "data_date": data_date,
        "is_today": data_date == generated_at.strftime("%Y-%m-%d"),
        "session_status": session_status(generated_at, data_date),
        "indexes": indexes,
        "market": market,
        "stocks": stocks,
        "industry_map": industry_map,
        "limit_ups": limit_ups,
        "hot_lists": hot_lists,
        "themes": themes,
        "sector_tables": sector_tables,
        "resonance": resonance,
        "top_amount": top_amount,
        "top_turnover": top_turnover,
        "top_amplitude": top_amplitude,
        "sources": sources.as_list(),
        "warnings": warnings,
    }


def session_status(generated_at: datetime, data_date: str) -> str:
    today = generated_at.strftime("%Y-%m-%d")
    if data_date != today:
        return "非交易日/最近交易日"
    minutes = generated_at.hour * 60 + generated_at.minute
    if minutes < 9 * 60 + 30:
        return "盘前"
    if minutes < 15 * 60:
        return "盘中"
    if minutes < 15 * 60 + 30:
        return "已收盘（数据结算中）"
    return "收盘"
