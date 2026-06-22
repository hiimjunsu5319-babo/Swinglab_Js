# -*- coding: utf-8 -*-
import contextlib
import datetime as dt
import io
import json
import math
import re
import threading
from pathlib import Path
from zoneinfo import ZoneInfo

from service.naver_scraper import BASE, clean_cell, fetch_html, fetch_naver_snapshot, parse_int
from service.naver_top10_service import is_excluded_stock


KST = ZoneInfo("Asia/Seoul")
CACHE_FILE = Path("data") / "candidate_cache.json"
CACHE_FILE.parent.mkdir(exist_ok=True)
REFRESH_SECONDS = 30 * 60
_LOCK = threading.Lock()
_MEMORY_CACHE = None


def get_candidates(force=False):
    with _LOCK:
        cache = load_cache()
        if cache and not force and not should_refresh(cache):
            return with_runtime_status(cache)

    try:
        payload = scan_candidates()
        save_cache(payload)
        return payload
    except Exception as exc:
        cache = load_cache()
        if cache:
            stale = with_runtime_status(cache)
            stale["error"] = f"매수 후보 갱신 실패: {exc}"
            stale["cache_status"] = "stale"
            return stale
        return empty_payload(f"매수 후보 데이터를 가져올 수 없습니다: {exc}")


def refresh_candidates():
    return get_candidates(force=True)


def scan_candidates():
    now = now_kst()
    updated_at = now.strftime("%Y-%m-%d %H:%M:%S")
    pool = fetch_trading_value_leaders(limit=100, updated_at=updated_at)
    scored = []
    strict = []
    for item in pool:
        try:
            detail = analyze_candidate(item)
            if detail:
                scored.append(detail)
            if detail and passes_core_filter(detail):
                strict.append(detail)
        except Exception:
            continue

    scored.sort(key=lambda row: row["score"], reverse=True)
    strict.sort(key=lambda row: row["score"], reverse=True)
    strict_tickers = {item["ticker"] for item in strict}
    selected = sorted(scored, key=lambda row: row["score"], reverse=True)
    top20 = selected[:20]
    for index, item in enumerate(top20, 1):
        item["rank"] = index
        item["selectionMode"] = "strict" if item["ticker"] in strict_tickers else "watchlist"
    selection_mode = "strict_plus_watchlist" if strict and len(top20) > len(strict) else ("strict" if strict else "watchlist")

    return {
        "updated_at": updated_at,
        "timezone": "Asia/Seoul",
        "source": "naver_finance + pykrx",
        "is_market_hours": is_market_hours(now),
        "is_intraday": is_market_hours(now),
        "cache_status": "fresh",
        "universe_count": len(pool),
        "analyzed_count": len(scored),
        "strict_count": len(strict),
        "selection_mode": selection_mode,
        "items": top20,
        "note": build_note(strict, scored, len(top20)),
    }


def build_note(strict, scored, selected_count=0):
    if strict:
        if selected_count > len(strict):
            return "장중 데이터는 잠정치입니다. 엄격 조건 통과 종목을 먼저 표시하고, 남은 자리는 점수 높은 관찰 후보로 채웠습니다."
        return "장중 데이터는 잠정치입니다. 엄격 조건을 통과한 종목을 점수순으로 표시합니다."
    if scored:
        return "엄격 조건을 모두 만족한 종목은 없어, 거래대금 상위 종목 중 점수순 관찰 후보를 표시합니다. 장중 데이터는 잠정치입니다."
    return "분석 가능한 후보를 찾지 못했습니다. 네이버 금융 또는 pykrx 응답 상태를 확인해 주세요."


def fetch_trading_value_leaders(limit=100, updated_at=""):
    rows = []
    seen = set()
    for sosok, market in [("0", "KOSPI"), ("1", "KOSDAQ")]:
        for page in range(1, 6):
            url = f"{BASE}/sise/sise_quant.naver?sosok={sosok}&page={page}"
            body = fetch_html(url)
            parsed = parse_trading_rows(body, market, updated_at)
            if not parsed:
                break
            for item in parsed:
                if item["ticker"] in seen or is_excluded_stock(item["name"]):
                    continue
                seen.add(item["ticker"])
                rows.append(item)
            if len(rows) >= limit:
                break
        if len(rows) >= limit:
            break
    rows.sort(key=lambda item: item.get("tradingValue") or 0, reverse=True)
    for index, item in enumerate(rows[:limit], 1):
        item["tradingValueRank"] = index
    return rows[:limit]


def parse_trading_rows(body, market, updated_at):
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.DOTALL | re.IGNORECASE):
        code_match = re.search(r"code=(\d{6})", tr)
        name_match = re.search(r'class="(?:tltle|company)"[^>]*>(.*?)</a>', tr, re.DOTALL | re.IGNORECASE)
        if not code_match or not name_match:
            continue
        cells = [clean_cell(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL | re.IGNORECASE)]
        numbers = [parse_int(cell) for cell in cells if re.search(r"\d", cell)]
        current_price = numbers[0] if numbers else None
        volume = numbers[3] if len(numbers) >= 4 else None
        trading_value = numbers[4] * 1_000_000 if len(numbers) >= 5 else None
        rows.append(
            {
                "ticker": code_match.group(1),
                "name": clean_cell(name_match.group(1)),
                "market": market,
                "currentPrice": current_price,
                "volume": volume,
                "tradingValue": trading_value,
                "changeRate": parse_change_rate(cells),
                "source": "naver_finance",
                "updated_at": updated_at,
            }
        )
    return rows


def analyze_candidate(seed):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from pykrx import stock

    today = dt.date.today()
    start = today - dt.timedelta(days=430)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        ohlcv = stock.get_market_ohlcv_by_date(fmt(start), fmt(today), seed["ticker"])
    if ohlcv is None or ohlcv.empty or len(ohlcv.dropna()) < 120:
        return None
    ohlcv = ohlcv.dropna()
    closes = ohlcv["종가"]
    highs = ohlcv["고가"]
    volumes = ohlcv["거래량"]
    latest = ohlcv.iloc[-1]
    close = to_number(latest.get("종가"))
    krx_volume = to_number(latest.get("거래량"))

    try:
        naver = fetch_naver_snapshot(seed["ticker"], include_image=False, include_rank=False)
    except Exception:
        naver = {}
    flow = naver.get("flow", {})
    flow_rows = naver.get("flowRows", [])
    current_price = naver.get("currentPrice") or seed.get("currentPrice") or close
    volume = naver.get("volume") or seed.get("volume") or krx_volume
    trading_value = naver.get("tradingValue") or seed.get("tradingValue")
    market_cap = naver.get("marketCap")
    foreign_holding_rate = naver.get("foreignHoldingRate")

    ma5 = moving_average(closes, 5)
    ma20 = moving_average(closes, 20)
    ma60 = moving_average(closes, 60)
    ma120 = moving_average(closes, 120)
    regular = all(value is not None for value in [ma5, ma20, ma60, ma120]) and ma5 > ma20 > ma60 > ma120
    ma5_near_ma20 = ma5 is not None and ma20 and ma5 >= ma20 * 0.985
    ma20_near_ma60 = ma20 is not None and ma60 and ma20 >= ma60 * 0.985
    ma20_support = ma20 is not None and current_price is not None and current_price >= ma20 * 0.98

    avg_volume20 = to_number(volumes.iloc[:-1].tail(20).mean()) if len(volumes) > 20 else None
    volume_ratio = volume / avg_volume20 if volume and avg_volume20 else None
    trading_values = closes * volumes
    avg_trading_value5 = to_number(trading_values.iloc[:-1].tail(5).mean()) if len(trading_values) > 5 else None
    avg_trading_value20 = to_number(trading_values.iloc[:-1].tail(20).mean()) if len(trading_values) > 20 else None
    trading_persistence = calc_trading_persistence(avg_trading_value5, avg_trading_value20, trading_value)
    week52_high = to_number(highs.tail(252).max())
    week52_low = to_number(ohlcv["저가"].tail(252).min())
    from_high = pct_from(current_price, week52_high)
    prior60 = to_number(highs.iloc[:-1].tail(60).max()) if len(highs) > 61 else None
    breakout = interpret_breakout(current_price, prior60)
    prior_distance = pct_from(current_price, prior60)
    change_rate = naver.get("changeRate") if naver.get("changeRate") is not None else seed.get("changeRate")
    uptrend20 = is_uptrend20(closes)
    foreign_holding_increase = calc_foreign_holding_increase(flow_rows)
    theme_score = score_theme(seed.get("name", ""))

    scores = score_swing_candidate(
        flow=flow,
        foreign_holding_rate=foreign_holding_rate,
        foreign_holding_increase=foreign_holding_increase,
        regular=regular,
        ma5_near_ma20=ma5_near_ma20,
        ma20_near_ma60=ma20_near_ma60,
        ma20_support=ma20_support,
        uptrend20=uptrend20,
        trading_rank=seed.get("tradingValueRank"),
        avg_trading_value5=avg_trading_value5,
        avg_trading_value20=avg_trading_value20,
        trading_persistence=trading_persistence,
        from_high=from_high,
        prior_distance=prior_distance,
        breakout=breakout,
        volume_ratio=volume_ratio,
        trading_value=trading_value,
        change_rate=change_rate,
        market_cap=market_cap,
        theme_score=theme_score,
    )

    return {
        "rank": 0,
        "ticker": seed["ticker"],
        "name": seed["name"],
        "market": seed["market"],
        "score": round(scores["total"], 1),
        "scores": scores,
        "currentPrice": current_price,
        "changeRate": change_rate,
        "volume": volume,
        "tradingValue": trading_value,
        "tradingValueRank": seed.get("tradingValueRank"),
        "avgTradingValue5": avg_trading_value5,
        "avgTradingValue20": avg_trading_value20,
        "tradingValuePersistence": trading_persistence,
        "marketCap": market_cap,
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "ma120": ma120,
        "regularAlignment": regular,
        "nearAlignment": bool(ma5_near_ma20 and ma20_near_ma60),
        "ma20Support": bool(ma20_support),
        "uptrend20": bool(uptrend20),
        "week52High": week52_high,
        "week52Low": week52_low,
        "from52wHighPercent": from_high,
        "priorHighDistancePercent": prior_distance,
        "breakoutStatus": breakout,
        "foreign5": flow.get("foreign5"),
        "foreign20": flow.get("foreign20"),
        "institution5": flow.get("institution5"),
        "institution20": flow.get("institution20"),
        "foreignHoldingRate": foreign_holding_rate,
        "foreignHoldingIncrease": foreign_holding_increase,
        "themeScore": theme_score,
        "volumeIncreaseRate": volume_ratio,
        "source": "naver_finance + pykrx",
        "updated_at": now_kst().strftime("%Y-%m-%d %H:%M:%S"),
    }


def passes_core_filter(item):
    checks = [
        (item.get("foreign20") or 0) > 0,
        (item.get("institution20") or 0) > 0,
        (item.get("tradingValueRank") or 9999) <= 100,
        bool(item.get("regularAlignment") or item.get("nearAlignment")),
        (item.get("marketCap") or 0) >= 500_000_000_000,
    ]
    if checks.count(False) >= 2:
        return False
    if (item.get("changeRate") or 0) >= 20:
        return False
    if (item.get("changeRate") or 0) <= -10:
        return False
    if (item.get("avgTradingValue20") or 0) < 5_000_000_000:
        return False
    from_high = item.get("from52wHighPercent")
    if from_high is None or from_high < -30:
        return False
    return True


def score_swing_candidate(**kwargs):
    flow = kwargs["flow"]
    foreign20 = flow.get("foreign20") or 0
    institution20 = flow.get("institution20") or 0
    foreign5 = flow.get("foreign5") or 0
    institution5 = flow.get("institution5") or 0

    supply = 0
    if foreign20 > 0:
        supply += 12
    if institution20 > 0:
        supply += 12
    if foreign20 > 0 and institution20 > 0:
        supply += 6
    if foreign5 > 0 and institution5 > 0:
        supply += 4
    elif foreign5 > 0 or institution5 > 0:
        supply += 2
    if kwargs.get("foreign_holding_increase"):
        supply += 4
    supply = min(40, supply)

    chart = 0
    chart += 12 if kwargs["regular"] else 0
    chart += 5 if kwargs["ma5_near_ma20"] else 0
    chart += 5 if kwargs["ma20_near_ma60"] else 0
    chart += 4 if kwargs.get("ma20_support") else 0
    chart += 4 if kwargs.get("uptrend20") else 0
    prior_distance = kwargs.get("prior_distance")
    if prior_distance is not None and -8 <= prior_distance <= 3:
        chart += 3
    breakout_text = str(kwargs.get("breakout") or "")
    if "돌파" in breakout_text or "근처" in breakout_text:
        chart += 2
    chart = min(30, chart)

    rank = kwargs["trading_rank"] or 100
    rank_score = max(0, 8 - ((rank - 1) / 99) * 8)
    avg5 = kwargs.get("avg_trading_value5") or 0
    avg20 = kwargs.get("avg_trading_value20") or 0
    trading_score = rank_score
    if avg20 >= 50_000_000_000:
        trading_score += 5
    elif avg20 >= 20_000_000_000:
        trading_score += 4
    elif avg20 >= 10_000_000_000:
        trading_score += 3
    elif avg20 >= 5_000_000_000:
        trading_score += 1.5
    persistence = kwargs.get("trading_persistence") or 0
    if 0.8 <= persistence <= 1.8:
        trading_score += 5
    elif 0.6 <= persistence <= 2.4:
        trading_score += 3
    if avg5 and avg20 and avg5 >= avg20:
        trading_score += 2
    trading_score = min(20, trading_score)

    theme = min(10, kwargs.get("theme_score") or 0)

    risk_penalty = 0
    change_rate = kwargs.get("change_rate")
    if change_rate is not None:
        if change_rate >= 20:
            risk_penalty += 45
        elif change_rate >= 12:
            risk_penalty += 28
        elif change_rate >= 7:
            risk_penalty += 18
        elif change_rate >= 5:
            risk_penalty += 8
        if change_rate <= -8:
            risk_penalty += 22
        elif change_rate <= -5:
            risk_penalty += 12
        elif change_rate <= -3:
            risk_penalty += 5

    market_cap = kwargs.get("market_cap") or 0
    if market_cap and market_cap <= 300_000_000_000:
        risk_penalty += 15
    elif market_cap and market_cap < 500_000_000_000:
        risk_penalty += 7
    if institution20 <= 0:
        risk_penalty += 12
    elif institution20 < 1_000_000_000:
        risk_penalty += 5
    holding_rate = kwargs.get("foreign_holding_rate")
    if holding_rate is not None and holding_rate <= 1:
        risk_penalty += 8
    if avg20 < 5_000_000_000:
        risk_penalty += 10

    total = max(0, min(100, supply + chart + trading_score + theme - risk_penalty))
    if change_rate is not None:
        if change_rate >= 20:
            total = min(total, 45)
        elif change_rate >= 12:
            total = min(total, 55)
        elif change_rate >= 7:
            total = min(total, 65)
    return {
        "total": total,
        "supply": round(supply, 1),
        "chart": round(chart, 1),
        "tradingValue": round(trading_score, 1),
        "theme": round(theme, 1),
        "riskPenalty": round(risk_penalty, 1),
    }


def calc_trading_persistence(avg5, avg20, current_value):
    if not avg20:
        return None
    base = avg5 or current_value or 0
    return base / avg20 if base else None


def calc_foreign_holding_increase(rows):
    if not rows or len(rows) < 5:
        return False
    latest = rows[0].get("foreignRate")
    past = rows[min(len(rows) - 1, 19)].get("foreignRate")
    return latest is not None and past is not None and latest > past


def is_uptrend20(closes):
    recent = closes.dropna().tail(20)
    if len(recent) < 20:
        return False
    first = to_number(recent.iloc[0])
    last = to_number(recent.iloc[-1])
    ma_first = to_number(recent.head(5).mean())
    ma_last = to_number(recent.tail(5).mean())
    return bool(first and last and ma_first and ma_last and last > first and ma_last > ma_first)


def score_theme(name):
    text = str(name or "").upper()
    keywords = [
        "전력", "전선", "변압", "LS", "효성중공업", "HD현대일렉트릭",
        "조선", "중공업", "오션", "방산", "한화에어로", "현대로템",
        "반도체", "하이닉스", "HPSP", "리노공업", "AI", "데이터", "전력망",
    ]
    return 10 if any(keyword.upper() in text for keyword in keywords) else 0


def score_candidate(**kwargs):
    flow = kwargs["flow"]
    supply = 0
    if (flow.get("foreign20") or 0) > 0:
        supply += 12
    if (flow.get("institution20") or 0) > 0:
        supply += 12
    if (flow.get("foreign5") or 0) > 0:
        supply += 5.5
    if (flow.get("institution5") or 0) > 0:
        supply += 5.5

    chart = 0
    chart += 12 if kwargs["regular"] else 0
    chart += 8 if kwargs["ma5_near_ma20"] else 0
    chart += 8 if kwargs["ma20_near_ma60"] else 0
    chart += 2 if "돌파" in str(kwargs["breakout"]) or "근처" in str(kwargs["breakout"]) else 0

    rank = kwargs["trading_rank"] or 100
    trading_score = max(0, 20 - ((rank - 1) / 99) * 20)
    if kwargs.get("trading_value"):
        trading_score = min(20, trading_score + 2)

    from_high = kwargs["from_high"]
    approach = 0 if from_high is None else max(0, 10 - min(abs(from_high), 20) / 20 * 10)
    volume = 0
    ratio = kwargs["volume_ratio"]
    if ratio is not None:
        if ratio >= 2:
            volume = 5
        elif ratio >= 1:
            volume = 4
        elif ratio >= 0.7:
            volume = 3

    risk_penalty = 0
    change_rate = kwargs.get("change_rate")
    if change_rate is not None:
        if change_rate <= -8:
            risk_penalty = 30
        elif change_rate <= -5:
            risk_penalty = 18
        elif change_rate <= -3:
            risk_penalty = 8

    total = max(0, min(100, supply + chart + trading_score + approach + volume - risk_penalty))
    return {
        "total": total,
        "supply": round(supply, 1),
        "chart": round(chart, 1),
        "tradingValue": round(trading_score, 1),
        "breakoutApproach": round(approach, 1),
        "volume": round(volume, 1),
        "riskPenalty": round(risk_penalty, 1),
    }


def load_cache():
    global _MEMORY_CACHE
    if _MEMORY_CACHE:
        return _MEMORY_CACHE
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
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
    if not is_market_hours(now_kst()):
        return False
    updated = parse_updated_at(cache.get("updated_at"))
    if not updated:
        return True
    return (now_kst() - updated).total_seconds() >= REFRESH_SECONDS


def with_runtime_status(payload):
    copy = dict(payload)
    copy["is_market_hours"] = is_market_hours(now_kst())
    copy.setdefault("cache_status", "cached")
    return copy


def empty_payload(error):
    return {
        "updated_at": "",
        "timezone": "Asia/Seoul",
        "source": "naver_finance + pykrx",
        "is_market_hours": is_market_hours(now_kst()),
        "is_intraday": is_market_hours(now_kst()),
        "cache_status": "empty",
        "universe_count": 0,
        "items": [],
        "note": "장중 데이터는 잠정치입니다.",
        "error": error,
    }


def parse_change_rate(cells):
    for cell in cells:
        match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", cell)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def moving_average(series, window):
    if len(series) < window:
        return None
    return to_number(series.tail(window).mean())


def to_number(value):
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def pct_from(current, high):
    if not current or not high:
        return None
    return (current / high - 1) * 100


def interpret_breakout(current, prior_high):
    if not current or not prior_high:
        return "데이터 없음"
    if current >= prior_high:
        return "전고점 돌파"
    gap = (prior_high - current) / prior_high * 100
    if gap <= 3:
        return "전고점 근처"
    return "아직 돌파 전"


def fmt(date):
    return date.strftime("%Y%m%d")


def parse_updated_at(value):
    if not value:
        return None
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
    except ValueError:
        return None


def is_market_hours(now):
    return now.weekday() < 5 and 9 <= now.hour <= 16


def now_kst():
    return dt.datetime.now(KST)
