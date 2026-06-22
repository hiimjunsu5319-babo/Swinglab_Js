# -*- coding: utf-8 -*-
import datetime as dt
import contextlib
import io
import math
import threading
import time

with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    from pykrx import stock

from service.naver_scraper import fetch_deal_rankings


CACHE_SECONDS = 15 * 60
_CACHE = {"created": 0, "payload": None}
_LOCK = threading.Lock()


def scan_rankings(limit=10, force=False):
    now = time.time()
    with _LOCK:
        if not force and _CACHE["payload"] and now - _CACHE["created"] < CACHE_SECONDS:
            return _CACHE["payload"]

    rankings = fetch_deal_rankings(limit=40)
    combined = rankings["combined"]
    regular_items = []

    for item in combined[:30]:
        trend = get_trend_snapshot(item["ticker"])
        item.update(trend)
        if item.get("regularAlignment"):
            regular_items.append(item)
        if len(regular_items) >= limit:
            break

    payload = {
        "updatedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "flowTop": rankings.get("combinedSell", [])[:limit],
        "regularFlowTop": regular_items[:limit],
        "foreignTop": rankings["foreign"][:limit],
        "institutionTop": rankings["institution"][:limit],
        "note": "위쪽 목록은 네이버 금융 외국인/기관 순매도 상위, 정배열 목록은 순매수 상위 기준입니다.",
    }

    with _LOCK:
        _CACHE["created"] = now
        _CACHE["payload"] = payload
    return payload


def get_trend_snapshot(ticker):
    try:
        today = dt.date.today()
        start = today - dt.timedelta(days=220)
        frame = stock.get_market_ohlcv_by_date(fmt(start), fmt(today), ticker)
        if frame is None or frame.empty:
            return trend_empty()

        close_col = pick_column(frame, ["종가", "close"])
        if close_col is None:
            return trend_empty()

        closes = frame[close_col].dropna()
        if len(closes) < 120:
            return trend_empty()

        ma5 = to_number(closes.tail(5).mean())
        ma20 = to_number(closes.tail(20).mean())
        ma60 = to_number(closes.tail(60).mean())
        ma120 = to_number(closes.tail(120).mean())
        current = to_number(closes.iloc[-1])
        regular = all_not_none([ma5, ma20, ma60, ma120]) and ma5 > ma20 > ma60 > ma120
        return {
            "currentPrice": current,
            "ma5": ma5,
            "ma20": ma20,
            "ma60": ma60,
            "ma120": ma120,
            "regularAlignment": regular,
        }
    except Exception:
        return trend_empty()


def trend_empty():
    return {
        "currentPrice": None,
        "ma5": None,
        "ma20": None,
        "ma60": None,
        "ma120": None,
        "regularAlignment": False,
    }


def pick_column(frame, candidates):
    normalized = {str(column).replace(" ", "").lower(): column for column in frame.columns}
    for candidate in candidates:
        key = candidate.replace(" ", "").lower()
        if key in normalized:
            return normalized[key]
    return None


def all_not_none(values):
    return all(value is not None for value in values)


def to_number(value):
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
        return int(round(float(value)))
    except Exception:
        return None


def fmt(value):
    if isinstance(value, dt.datetime):
        value = value.date()
    return value.strftime("%Y%m%d")
