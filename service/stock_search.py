# -*- coding: utf-8 -*-
import contextlib
import datetime as dt
import io
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from service.naver_scraper import fetch_html


CACHE_PATH = Path("data") / "stock_universe.json"
_CACHE = {"created": None, "data": None, "source": ""}


class StockSearchError(RuntimeError):
    def __init__(self, message, candidates=None):
        super().__init__(message)
        self.candidates = candidates or []


def load_pykrx_stock():
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from pykrx import stock as pykrx_stock
        return pykrx_stock
    except ModuleNotFoundError:
        return None


def resolve_stock(query):
    value = (query or "").strip()
    if not value:
        raise StockSearchError("종목을 찾을 수 없습니다. 종목명 또는 6자리 종목코드를 확인해 주세요.")

    universe = get_stock_universe()
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 6:
        item = universe.get(digits) if universe else None
        if item:
            return digits, item["name"], item["market"], "", item.get("source", "pykrx")
        item = resolve_code_from_naver(digits)
        if item:
            save_cache_item(item)
            return digits, item["name"], item.get("market", "UNKNOWN"), "네이버 금융 검색 fallback으로 종목을 확인했습니다.", "naver_fallback"
        raise StockSearchError("pykrx 종목 DB와 네이버 금융 검색 모두 실패했습니다. 네트워크 상태를 확인해 주세요.")

    normalized = normalize_name(value)
    if universe:
        exact = [{"ticker": ticker, **item} for ticker, item in universe.items() if normalize_name(item["name"]) == normalized]
        if len(exact) == 1:
            item = exact[0]
            return item["ticker"], item["name"], item["market"], "", item.get("source", "pykrx")
        if len(exact) > 1:
            raise StockSearchError("동일한 종목명이 여러 개 있습니다. 아래 후보 중 하나를 선택해 주세요.", exact)

        partial = [{"ticker": ticker, **item} for ticker, item in universe.items() if normalized and normalized in normalize_name(item["name"])][:20]
        if len(partial) == 1:
            item = partial[0]
            return item["ticker"], item["name"], item["market"], "부분 일치 종목을 찾았습니다.", item.get("source", "pykrx")
        if len(partial) > 1:
            raise StockSearchError("부분 일치 종목이 여러 개 있습니다. 아래 후보 중 하나를 선택해 주세요.", partial)

    candidates = search_name_from_naver(value)
    exact = [item for item in candidates if normalize_name(item.get("name", "")) == normalized]
    selected = exact[:1] or candidates[:1]
    if len(exact) == 1 or len(candidates) == 1:
        item = selected[0]
        save_cache_item(item)
        return item["ticker"], item["name"], item.get("market", "UNKNOWN"), "네이버 금융 검색 fallback으로 종목을 확인했습니다.", "naver_fallback"
    if candidates:
        for item in candidates:
            save_cache_item(item)
        raise StockSearchError("부분 일치 종목이 여러 개 있습니다. 아래 후보 중 하나를 선택해 주세요.", candidates[:20])

    raise StockSearchError("pykrx 종목 DB와 네이버 금융 검색 모두 실패했습니다. 네트워크 상태를 확인해 주세요.")


def get_stock_universe():
    today = dt.date.today()
    if _CACHE["created"] == today and _CACHE["data"] is not None:
        return _CACHE["data"]

    universe = load_pykrx_universe()
    if universe:
        save_cache(universe)
        _CACHE.update({"created": today, "data": universe, "source": "pykrx"})
        return universe

    cached = load_cache()
    _CACHE.update({"created": today, "data": cached, "source": "cache"})
    return cached


def load_pykrx_universe():
    pykrx_stock = load_pykrx_stock()
    if pykrx_stock is None:
        return {}

    today = dt.date.today()
    for offset in range(0, 15):
        date = (today - dt.timedelta(days=offset)).strftime("%Y%m%d")
        universe = {}
        for market in ["KOSPI", "KOSDAQ"]:
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    tickers = pykrx_stock.get_market_ticker_list(date, market=market)
                for ticker in tickers:
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        name = pykrx_stock.get_market_ticker_name(ticker)
                    if name:
                        universe[ticker] = {
                            "ticker": ticker,
                            "name": name,
                            "market": market,
                            "source": "pykrx",
                            "updated_at": now_text(),
                        }
            except Exception:
                continue
        if universe:
            return universe
    return {}


def resolve_code_from_naver(ticker):
    try:
        body = fetch_html(f"https://finance.naver.com/item/main.naver?code={ticker}")
    except Exception:
        return None
    if ticker not in body:
        return None
    text = strip_tags(body)
    name_match = re.search(r"종목명\s+(.+?)\s+종목코드", text)
    if not name_match:
        name_match = re.search(r"<h2><a[^>]*>(.*?)</a>", body, re.DOTALL)
    code_match = re.search(r"종목코드\s*(\d{6})\s*(코스피|코스닥)?", text)
    market_text = code_match.group(2) if code_match and code_match.lastindex and code_match.group(2) else ""
    return {
        "ticker": ticker,
        "name": clean_cell(name_match.group(1)) if name_match else ticker,
        "market": market_from_text(market_text or body),
        "source": "naver_fallback",
        "updated_at": now_text(),
    }


def search_name_from_naver(query):
    results = []
    results.extend(search_naver_autocomplete(query))
    if not results:
        results.extend(search_naver_web(query))
    unique = {}
    for item in results:
        if is_ticker(item.get("ticker", "")):
            unique[item["ticker"]] = item
    return list(unique.values())


def search_naver_autocomplete(query):
    url = "https://ac.finance.naver.com/ac?" + urllib.parse.urlencode(
        {"q": query, "target": "stock,ipo,index,marketindicator"}
    )
    try:
        body = fetch_text(url, encoding="utf-8", referer="https://finance.naver.com/search/search.naver")
    except Exception:
        return []
    try:
        data = json.loads(body.strip())
    except Exception:
        return []
    found = []

    def walk(value):
        if isinstance(value, dict):
            text = " ".join(str(v) for v in value.values())
            append_from_text(text)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            append_from_text(" ".join(str(v) for v in value))
            for child in value:
                walk(child)

    def append_from_text(text):
        match = re.search(r"\b(\d{6})\b", text)
        if not match:
            return
        ticker = match.group(1)
        name = infer_name_from_text(text, ticker) or ticker
        found.append({"ticker": ticker, "name": name, "market": market_from_text(text), "source": "naver_fallback", "updated_at": now_text()})

    walk(data)
    return found


def search_naver_web(query):
    bodies = []
    for search_query in [f"{query} 네이버 금융", f"{query} 주가", query]:
        url = "https://search.naver.com/search.naver?" + urllib.parse.urlencode(
            {"where": "nexearch", "sm": "top_hty", "query": search_query}
        )
        try:
            bodies.append(fetch_text(url, encoding="utf-8"))
        except Exception:
            continue
    results = []
    for body in bodies:
        codes = set()
        for match in re.findall(r"code=(\d{6})|/stock/(\d{6})|종목코드\s*:?\s*(\d{6})", body):
            codes.add(next(code for code in match if code))
        for code in sorted(codes):
            item = resolve_code_from_naver(code)
            if item and normalize_name(query) in normalize_name(item.get("name", "")):
                results.append(item)
    return results


def infer_name_from_text(text, ticker):
    cleaned = clean_cell(text)
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    parts = [part for part in re.split(r"[\s|,/]+", cleaned) if part and part != ticker]
    for part in parts:
        if not re.search(r"\d", part) and "KOS" not in part.upper() and len(part) <= 30:
            return part
    return ""


def load_cache():
    if not CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    rows = data.get("items", data if isinstance(data, list) else [])
    universe = {}
    for row in rows:
        ticker = str(row.get("ticker", "")).strip()
        if is_ticker(ticker):
            universe[ticker] = {
                "ticker": ticker,
                "name": row.get("name") or ticker,
                "market": row.get("market") or "UNKNOWN",
                "source": row.get("source") or "cache",
                "updated_at": row.get("updated_at") or "",
            }
    return universe


def save_cache(universe):
    if not universe:
        return
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    items = list(sorted(universe.values(), key=lambda item: item["ticker"]))
    CACHE_PATH.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")


def save_cache_item(item):
    universe = load_cache()
    ticker = str(item.get("ticker", "")).strip()
    if not is_ticker(ticker):
        return
    universe[ticker] = {
        "ticker": ticker,
        "name": item.get("name") or ticker,
        "market": item.get("market") or "UNKNOWN",
        "source": item.get("source") or "naver_fallback",
        "updated_at": now_text(),
    }
    save_cache(universe)


def fetch_text(url, encoding="utf-8", referer="https://finance.naver.com"):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer})
    with urllib.request.urlopen(req, timeout=10) as response:
        data = response.read()
    return data.decode(encoding, errors="ignore")


def normalize_name(value):
    return re.sub(r"\s+", "", str(value or "")).upper()


def clean_cell(value):
    text = re.sub(r"<[^>]+>", " ", str(value))
    return re.sub(r"\s+", " ", text).strip()


def strip_tags(value):
    return clean_cell(value)


def market_from_text(value):
    text = str(value)
    upper = text.upper()
    if "KOSDAQ" in upper or "코스닥" in text:
        return "KOSDAQ"
    if "KOSPI" in upper or "코스피" in text:
        return "KOSPI"
    return "UNKNOWN"


def is_ticker(value):
    return len(str(value)) == 6 and str(value).isdigit()


def now_text():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
