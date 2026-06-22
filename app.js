# -*- coding: utf-8 -*-
import datetime as dt
import json
import re
import threading
from pathlib import Path
from zoneinfo import ZoneInfo

from service.naver_scraper import BASE, clean_cell, fetch_html, parse_int


KST = ZoneInfo("Asia/Seoul")
CACHE_FILE = Path("data") / "top10_cache.json"
CACHE_FILE.parent.mkdir(exist_ok=True)
REFRESH_SECONDS = 60 * 60
_LOCK = threading.Lock()
_MEMORY_CACHE = None

EXCLUDE_KEYWORDS = [
    "ETF",
    "ETN",
    "KODEX",
    "TIGER",
    "ACE",
    "SOL",
    "KBSTAR",
    "HANARO",
    "ARIRANG",
    "KOSEF",
    "TIMEFOLIO",
    "PLUS",
    "히어로즈",
    "TREX",
    "QV",
    "스팩",
    "SPAC",
    "리츠",
]


def get_top10(force=False):
    with _LOCK:
        cache = load_cache()
        if not force and cache and not should_refresh(cache):
            return with_runtime_status(cache)

    try:
        payload = fetch_top10()
        save_cache(payload)
        return payload
    except Exception as exc:
        cache = load_cache()
        if cache:
            cached = with_runtime_status(cache)
            cached["error"] = f"네이버 금융 TOP10 갱신 실패: {exc}"
            cached["cache_status"] = "stale"
            return cached
        return empty_payload(f"TOP10 데이터를 가져올 수 없습니다: {exc}")


def refresh_top10():
    return get_top10(force=True)


def fetch_top10():
    now = now_kst()
    updated_at = now.strftime("%Y-%m-%d %H:%M:%S")
    foreign_buy = fetch_investor_rank("9000", "buy", updated_at)
    institution_buy = fetch_investor_rank("1000", "buy", updated_at)
    foreign_sell = fetch_investor_rank("9000", "sell", updated_at)
    institution_sell = fetch_investor_rank("1000", "sell", updated_at)
    combined_buy = combine_rankings(foreign_buy, institution_buy, updated_at, signed=True)
    combined_sell = combine_rankings(foreign_sell, institution_sell, updated_at, signed=False)

    return {
        "updated_at": updated_at,
        "timezone": "Asia/Seoul",
        "source": "naver_finance",
        "is_market_hours": is_market_hours(now),
        "cache_status": "fresh",
        "foreign_buy": foreign_buy,
        "foreign_sell": foreign_sell,
        "institution_buy": institution_buy,
        "institution_sell": institution_sell,
        "combined_buy": combined_buy,
        "combined_sell": combined_sell,
        "note": market_note(now),
    }


def fetch_investor_rank(investor_gubun, deal_type, updated_at, limit=10):
    rows = []
    for sosok, market in [("01", "KOSPI"), ("02", "KOSDAQ")]:
        for page in range(1, 8):
            url = (
                f"{BASE}/sise/sise_deal_rank_iframe.naver"
                f"?sosok={sosok}&investor_gubun={investor_gubun}&type={deal_type}&page={page}"
            )
            body = fetch_html(url)
            parsed = parse_rank_iframe(body, market, updated_at, deal_type)
            if not parsed:
                break
            rows.extend(parsed)
            if len(non_excluded(rows)) >= limit:
                break
    filtered = non_excluded(rows)
    filtered.sort(key=lambda item: abs(item.get("amount") or 0), reverse=True)
    return assign_rank(filtered[:limit])


def parse_rank_iframe(body, market, updated_at, deal_type):
    rows = []
    seen = set()
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.DOTALL | re.IGNORECASE):
        code_match = re.search(r"code=(\d{6})", tr)
        name_match = re.search(r'class="(?:company|tltle)"[^>]*>(.*?)</a>', tr, re.DOTALL | re.IGNORECASE)
        if not code_match or not name_match:
            continue
        ticker = code_match.group(1)
        if ticker in seen:
            continue
        seen.add(ticker)
        name = clean_cell(name_match.group(1))
        cells = [clean_cell(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL | re.IGNORECASE)]
        numbers = [parse_int(cell) for cell in cells if re.search(r"[-+]?\d", cell)]
        amount = (numbers[-2] if len(numbers) >= 2 else 0) * 1_000_000
        if deal_type == "sell":
            amount = -abs(amount)
        rows.append(
            {
                "rank": 0,
                "ticker": ticker,
                "name": name,
                "market": market,
                "amount": amount,
                "change_rate": parse_change_rate(cells),
                "source": "naver_finance",
                "updated_at": updated_at,
            }
        )
    return rows


def combine_rankings(first, second, updated_at, signed):
    by_ticker = {}
    for item in [*first, *second]:
        target = by_ticker.setdefault(
            item["ticker"],
            {
                "rank": 0,
                "ticker": item["ticker"],
                "name": item["name"],
                "market": item["market"],
                "amount": 0,
                "change_rate": item.get("change_rate"),
                "source": "naver_finance",
                "updated_at": updated_at,
            },
        )
        target["amount"] += item.get("amount") or 0
        if target.get("change_rate") is None:
            target["change_rate"] = item.get("change_rate")
    items = list(by_ticker.values())
    if signed:
        items = [item for item in items if item["amount"] > 0]
    else:
        items = [item for item in items if item["amount"] < 0]
    items.sort(key=lambda item: abs(item.get("amount") or 0), reverse=True)
    return assign_rank(items[:10])


def non_excluded(rows):
    return [row for row in rows if not is_excluded_stock(row.get("name", ""))]


def is_excluded_stock(name):
    upper = str(name).upper().replace(" ", "")
    if re.search(r"(\d+호)?스팩|SPAC", str(name), re.IGNORECASE):
        return True
    if re.search(r"(우|우B|우C)$", str(name)):
        return True
    return any(keyword.upper().replace(" ", "") in upper for keyword in EXCLUDE_KEYWORDS)


def assign_rank(items):
    for index, item in enumerate(items, 1):
        item["rank"] = index
    return items


def parse_change_rate(cells):
    for cell in cells:
        match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", cell)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def load_cache():
    global _MEMORY_CACHE
    if _MEMORY_CACHE:
        return _MEMORY_CACHE
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("updated_at"):
            _MEMORY_CACHE = data
            return data
    except (OSError, json.JSONDecodeError):
        return None
    return None


def save_cache(payload):
    global _MEMORY_CACHE
    _MEMORY_CACHE = payload
    CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def should_refresh(cache):
    now = now_kst()
    if not is_market_hours(now):
        return False
    updated = parse_updated_at(cache.get("updated_at"))
    if not updated:
        return True
    return (now - updated).total_seconds() >= REFRESH_SECONDS


def with_runtime_status(payload):
    now = now_kst()
    copy = dict(payload)
    copy["is_market_hours"] = is_market_hours(now)
    copy["note"] = market_note(now)
    copy.setdefault("cache_status", "cached")
    return copy


def empty_payload(error):
    now = now_kst()
    return {
        "updated_at": "",
        "timezone": "Asia/Seoul",
        "source": "naver_finance",
        "is_market_hours": is_market_hours(now),
        "cache_status": "empty",
        "foreign_buy": [],
        "foreign_sell": [],
        "institution_buy": [],
        "institution_sell": [],
        "combined_buy": [],
        "combined_sell": [],
        "note": market_note(now),
        "error": error,
    }


def market_note(now):
    if is_market_hours(now):
        return "한국시간 장중: 마지막 갱신 후 1시간이 지나면 자동으로 새로고침합니다."
    return "장외 시간: 마지막 갱신 데이터를 표시합니다."


def is_market_hours(now):
    return now.weekday() < 5 and 9 <= now.hour <= 16


def parse_updated_at(value):
    if not value:
        return None
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
    except ValueError:
        return None


def now_kst():
    return dt.datetime.now(KST)
