# -*- coding: utf-8 -*-
import datetime as dt
import contextlib
import io
import math

from service.naver_scraper import fetch_naver_snapshot, render_summary_image
from service.stock_search import StockSearchError, get_stock_universe, resolve_stock


class AnalysisError(RuntimeError):
    def __init__(self, message, candidates=None):
        super().__init__(message)
        self.candidates = candidates or []


def load_pykrx_stock():
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from pykrx import stock as pykrx_stock
        return pykrx_stock
    except ModuleNotFoundError as exc:
        raise AnalysisError("pykrx가 설치되어 있지 않습니다. pykrx 설치 후 dev 서버를 재시작해 주세요.") from exc


def analyze_stock(query, quote_mode="NAVER"):
    try:
        ticker, name, market, resolve_note, search_source = resolve_stock(query)
    except StockSearchError as exc:
        raise AnalysisError(str(exc), exc.candidates) from exc
    quote_mode = (quote_mode or "NAVER").upper()
    today = dt.date.today()
    start = today - dt.timedelta(days=430)

    pykrx_stock = load_pykrx_stock()
    ohlcv = pykrx_stock.get_market_ohlcv_by_date(fmt(start), fmt(today), ticker)
    if ohlcv is None or ohlcv.empty:
        raise AnalysisError("pykrx에서 시세 데이터를 가져오지 못했습니다. 종목명 또는 6자리 종목코드를 확인해 주세요.")

    ohlcv = ohlcv.dropna()
    if len(ohlcv) < 20:
        raise AnalysisError("분석에 필요한 거래일 데이터가 부족합니다.")

    latest_date = ohlcv.index[-1]
    latest = ohlcv.iloc[-1]
    close = to_number(latest.get("종가"))
    open_price = to_number(latest.get("시가"))
    high = to_number(latest.get("고가"))
    low = to_number(latest.get("저가"))
    volume = to_number(latest.get("거래량"))
    change_rate = to_float(latest.get("등락률"))

    closes = ohlcv["종가"]
    volumes = ohlcv["거래량"]
    highs = ohlcv["고가"]
    lows = ohlcv["저가"]

    naver = fetch_naver_snapshot(ticker)
    update_time = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_intraday = is_market_hours(dt.datetime.now())

    ma = {
        "ma5": moving_average(closes, 5),
        "ma20": moving_average(closes, 20),
        "ma60": moving_average(closes, 60),
        "ma120": moving_average(closes, 120),
    }
    display_price = naver.get("currentPrice") if quote_mode != "KRX" and naver.get("currentPrice") else close
    display_volume = naver.get("volume") if quote_mode != "KRX" and naver.get("volume") else volume
    display_trading_value = naver.get("tradingValue") if quote_mode != "KRX" and naver.get("tradingValue") else None
    ma_position = {
        "aboveMa5": compare_gt(display_price, ma["ma5"]),
        "aboveMa20": compare_gt(display_price, ma["ma20"]),
        "aboveMa60": compare_gt(display_price, ma["ma60"]),
        "aboveMa120": compare_gt(display_price, ma["ma120"]),
    }
    regular_alignment = all_not_none(ma.values()) and ma["ma5"] > ma["ma20"] > ma["ma60"] > ma["ma120"]
    reverse_alignment = all_not_none(ma.values()) and ma["ma5"] < ma["ma20"] < ma["ma60"] < ma["ma120"]

    average_volume20 = to_number(volumes.iloc[:-1].tail(20).mean()) if len(volumes) > 20 else to_number(volumes.tail(20).mean())
    volume_ratio = display_volume / average_volume20 if average_volume20 else None
    volume_level = interpret_volume_ratio(volume_ratio)

    estimated_trading_value = estimate_trading_value(open_price, high, low, close, volume)
    trading_value = display_trading_value or estimated_trading_value
    short_balance = analyze_short_balance(ticker, today)

    week52_high = to_number(highs.tail(252).max())
    week52_low = to_number(lows.tail(252).min())
    from_52w_high = pct_from(close, week52_high)

    prior60_high_series = highs.iloc[:-1].tail(60)
    prior60_high = to_number(prior60_high_series.max()) if not prior60_high_series.empty else None
    breakout_status = interpret_breakout(close, prior60_high)

    flow = naver.get("flow", {})
    notes = [resolve_note]
    if naver.get("error"):
        notes.append("네이버 금융 데이터를 가져올 수 없습니다.")
    elif not naver.get("available"):
        notes.append("네이버 금융 데이터를 가져올 수 없습니다.")

    analysis = build_analysis(
        ma_position=ma_position,
        regular_alignment=regular_alignment,
        reverse_alignment=reverse_alignment,
        volume_ratio=volume_ratio,
        volume_level=volume_level,
        flow=flow,
        from_52w_high=from_52w_high,
        breakout_status=breakout_status,
        trading_value_rank=naver.get("tradingValueRank"),
        market_interest=naver.get("marketInterest"),
    )

    result = {
        "ticker": ticker,
        "name": name or ticker,
        "market": market,
        "date": latest_date.strftime("%Y-%m-%d"),
        "source": "pykrx + 네이버 금융",
        "searchSource": search_source,
        "quoteMode": quote_mode,
        "isIntraday": is_intraday,
        "updatedAt": update_time,
        "dataSources": {
            "quote": (naver.get("quoteSourceDetail") or "네이버") if quote_mode != "KRX" and naver.get("currentPrice") else "KRX/pykrx",
            "ohlcv": "pykrx(KRX 일봉)",
            "movingAverage": "pykrx(KRX 일봉 종가)",
            "tradingValue": "네이버" if display_trading_value else "pykrx OHLCV 추정",
            "supply": "네이버 금융",
            "updatedAt": update_time,
            "naverUpdatedAt": naver.get("updatedAt"),
        },
        "notes": [note for note in notes if note],
        "basic": {
            "name": name or ticker,
            "ticker": ticker,
            "market": market,
            "currentPrice": display_price,
            "krxClose": close,
            "changeRate": change_rate,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": display_volume,
            "krxVolume": volume,
            "marketCap": naver.get("marketCap"),
        },
        "movingAverage": {
            **ma,
            **ma_position,
            "regularAlignment": regular_alignment,
            "reverseAlignment": reverse_alignment,
        },
        "volumeAnalysis": {
            "todayVolume": display_volume,
            "krxTodayVolume": volume,
            "averageVolume20": average_volume20,
            "volumeRatio": volume_ratio,
            "volumeIncreaseRate": volume_ratio,
            "volumeLevel": volume_level,
            "basis": "장중 기준" if is_intraday and quote_mode != "KRX" else "종가 기준",
        },
        "tradingValueAnalysis": {
            "tradingValue": trading_value,
            "estimatedTradingValue": estimated_trading_value,
            "rawTradingValue": naver.get("tradingValue"),
            "rawTradingValueText": naver.get("rawTradingValueText"),
            "rank": naver.get("tradingValueRank"),
            "marketInterest": naver.get("marketInterest"),
            "shortBalance": short_balance,
        },
        "week52": {
            "high": week52_high,
            "low": week52_low,
            "currentPrice": close,
            "fromHighPercent": from_52w_high,
        },
        "breakout": {
            "prior60High": prior60_high,
            "currentPrice": close,
            "status": breakout_status,
        },
        "validation": build_validation(
            quote_mode=quote_mode,
            is_intraday=is_intraday,
            update_time=update_time,
            naver=naver,
            latest_date=latest_date,
            display_price=display_price,
            display_volume=display_volume,
            trading_value=trading_value,
            estimated_trading_value=estimated_trading_value,
            close=close,
            volume=volume,
            ma=ma,
        ),
        "flow": {
            "foreign5": flow.get("foreign5"),
            "foreign20": flow.get("foreign20"),
            "institution5": flow.get("institution5"),
            "institution20": flow.get("institution20"),
            "individual5": flow.get("individual5"),
            "individual20": flow.get("individual20"),
            "foreignHoldingRate": naver.get("foreignHoldingRate"),
            "jointStatus": flow.get("jointStatus", "네이버 금융 데이터를 가져올 수 없습니다."),
            "available": flow.get("available", False),
            "imageUrl": naver.get("flowImageUrl", ""),
        },
        "analysis": analysis,
    }
    result["summaryImageUrl"] = render_summary_image(result, build_chart_rows(ohlcv), naver.get("flowRows", []))
    result["prompt"] = build_prompt(result)
    return result


def build_chart_rows(ohlcv):
    rows = []
    for date, row in ohlcv.tail(60).iterrows():
        rows.append(
            {
                "date": date.strftime("%m/%d") if hasattr(date, "strftime") else "",
                "close": to_number(row.get("종가")),
                "volume": to_number(row.get("거래량")),
            }
        )
    return rows


def analyze_short_balance(ticker, today):
    start = today - dt.timedelta(days=45)
    unavailable = {
        "available": False,
        "balance": None,
        "amount": None,
        "ratio": None,
        "change5": None,
        "source": "pykrx 공매도잔고",
        "date": "",
        "interpretation": "대차잔고 데이터를 가져올 수 없습니다.",
    }
    try:
        pykrx_stock = load_pykrx_stock()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            data = pykrx_stock.get_shorting_balance_by_date(fmt(start), fmt(today), ticker)
        if data is None or data.empty:
            return unavailable
        data = data.dropna()
        latest = data.iloc[-1]
        previous = data.iloc[-6] if len(data) >= 6 else data.iloc[0]
        balance = to_number(latest.get("공매도잔고"))
        amount = to_number(latest.get("공매도금액"))
        ratio = to_float(latest.get("비중"))
        previous_balance = to_number(previous.get("공매도잔고"))
        change5 = balance - previous_balance if balance is not None and previous_balance is not None else None
        return {
            "available": True,
            "balance": balance,
            "amount": amount,
            "ratio": ratio,
            "change5": change5,
            "source": "pykrx 공매도잔고",
            "date": data.index[-1].strftime("%Y-%m-%d") if hasattr(data.index[-1], "strftime") else str(data.index[-1]),
            "interpretation": interpret_short_balance(ratio, change5),
        }
    except Exception:
        return unavailable


def interpret_short_balance(ratio, change5):
    if ratio is None:
        return "대차잔고 비중을 계산할 수 없습니다."
    level = "낮은 편"
    if ratio >= 3:
        level = "높은 편"
    elif ratio >= 1:
        level = "중간 수준"
    direction = ""
    if change5 is not None:
        if change5 > 0:
            direction = "이며 최근 5거래일 잔고가 증가했습니다"
        elif change5 < 0:
            direction = "이며 최근 5거래일 잔고가 감소했습니다"
        else:
            direction = "이며 최근 5거래일 변화가 크지 않습니다"
    return f"대차/공매도 잔고 비중은 {level}{direction}."


def build_analysis(**kwargs):
    ma_position = kwargs["ma_position"]
    regular_alignment = kwargs["regular_alignment"]
    reverse_alignment = kwargs["reverse_alignment"]
    volume_ratio = kwargs["volume_ratio"]
    volume_level = kwargs["volume_level"]
    flow = kwargs["flow"]
    from_52w_high = kwargs["from_52w_high"]
    breakout_status = kwargs["breakout_status"]
    trading_value_rank = kwargs["trading_value_rank"]
    market_interest = kwargs["market_interest"]

    above_count = sum(1 for value in ma_position.values() if value is True)
    if regular_alignment and above_count == 4:
        trend = "정배열 상태이며 현재가가 모든 이동평균선 위에 위치합니다."
    elif reverse_alignment:
        trend = "역배열 상태로 중기 추세가 약한 구간입니다."
    elif above_count >= 3:
        trend = "현재가가 다수 이동평균선 위에 있어 추세 회복 신호가 있습니다."
    else:
        trend = "현재가가 주요 이동평균선 아래에 있어 추세 확인이 필요합니다."

    if volume_ratio is None:
        volume = "20일 평균 거래량을 계산할 수 없습니다."
    else:
        volume = f"거래량이 평균 대비 {volume_ratio:.2f}배 수준입니다. 해석: {volume_level}."

    if flow.get("available"):
        supply = f"최근 20일 기준 {flow.get('jointStatus')}입니다."
    else:
        supply = "네이버 금융 데이터를 가져올 수 없습니다."

    market = market_interest or "거래대금 순위 데이터를 가져올 수 없습니다."
    if trading_value_rank:
        market = f"거래대금 순위 {trading_value_rank}위. {market}"

    risk = []
    if volume_ratio is not None and volume_ratio < 1.3:
        risk.append("거래량 증가폭은 아직 제한적입니다.")
    if not regular_alignment:
        risk.append("정배열이 아니어서 추세 지속성 확인이 필요합니다.")
    if from_52w_high is not None and from_52w_high > -3:
        risk.append("52주 고점에 가까워 단기 변동성이 커질 수 있습니다.")
    if not risk:
        risk.append("현재 데이터상 두드러진 위험 신호는 제한적입니다.")

    observation = [
        "52주 고점 돌파 여부 확인 필요",
        f"전고점 상태: {breakout_status}",
    ]
    if flow.get("available"):
        observation.append("외국인/기관 20일 수급 지속 여부 확인")

    return {
        "trend": trend,
        "volume": volume,
        "flow": supply,
        "marketInterest": market,
        "risk": " ".join(risk),
        "observation": " · ".join(observation),
    }


def build_prompt(result):
    b = result["basic"]
    ma = result["movingAverage"]
    flow = result["flow"]
    week52 = result["week52"]
    breakout = result["breakout"]
    volume = result["volumeAnalysis"]
    trading = result["tradingValueAnalysis"]
    return "\n".join(
        [
            "글과 캡처사진 중 내용이 다른 부분은 사진을 우선으로 판단해 주세요.",
            "",
            f"종목: {result['name']}",
            f"종목코드: {result['ticker']}",
            f"시장: {result.get('market') or b.get('market') or '데이터 없음'}",
            f"현재가: {format_won(b['currentPrice'])}",
            f"등락률: {format_percent(b['changeRate'])}",
            f"시가총액: {format_won(b['marketCap'])}",
            f"거래량: {format_qty(b['volume'])}",
            f"거래대금: {format_big_money(trading['tradingValue'])}",
            f"거래대금 순위: {format_rank(trading['rank'])}",
            f"MA5: {format_won(ma['ma5'])}",
            f"MA20: {format_won(ma['ma20'])}",
            f"MA60: {format_won(ma['ma60'])}",
            f"MA120: {format_won(ma['ma120'])}",
            f"정배열 여부: {'예' if ma['regularAlignment'] else '아니오'}",
            f"52주 최고가: {format_won(week52['high'])}",
            f"52주 최저가: {format_won(week52['low'])}",
            f"전고점 돌파 여부: {breakout['status']}",
            f"외국인 5일: {format_eok(flow['foreign5'])}",
            f"외국인 20일: {format_eok(flow['foreign20'])}",
            f"기관 5일: {format_eok(flow['institution5'])}",
            f"기관 20일: {format_eok(flow['institution20'])}",
            f"외국인 보유율: {format_percent(flow['foreignHoldingRate'])}",
            f"거래량 증가율: {format_multiple(volume['volumeRatio'])}",
            "",
            "위 데이터를 바탕으로 추세, 수급, 거래량, 위험요인, 관찰포인트를 분석해 주세요.",
        ]
    )


def build_validation(**kwargs):
    ma = kwargs["ma"]
    naver = kwargs["naver"]
    return {
        "rows": [
            {"label": "화면 현재가", "raw": kwargs["display_price"], "converted": kwargs["display_price"], "source": (naver.get("quoteSourceDetail") or "네이버") if kwargs["quote_mode"] != "KRX" and naver.get("currentPrice") else "pykrx/KRX", "updatedAt": kwargs["update_time"]},
            {"label": "KRX 일봉 종가", "raw": kwargs["close"], "converted": kwargs["close"], "source": "pykrx(KRX 일봉)", "updatedAt": kwargs["latest_date"].strftime("%Y-%m-%d")},
            {"label": "화면 거래량", "raw": kwargs["display_volume"], "converted": kwargs["display_volume"], "source": (naver.get("quoteSourceDetail") or "네이버") if kwargs["quote_mode"] != "KRX" and naver.get("volume") else "pykrx/KRX", "updatedAt": kwargs["update_time"]},
            {"label": "네이버 원본 거래량", "raw": naver.get("rawVolumeText") or naver.get("volume"), "converted": naver.get("volume"), "source": naver.get("quoteSourceDetail") or "네이버", "updatedAt": naver.get("updatedAt") or kwargs["update_time"]},
            {"label": "KRX 일봉 거래량", "raw": kwargs["volume"], "converted": kwargs["volume"], "source": "pykrx(KRX 일봉)", "updatedAt": kwargs["latest_date"].strftime("%Y-%m-%d")},
            {"label": "원본 거래대금", "raw": naver.get("rawTradingValueText") or naver.get("tradingValue"), "converted": naver.get("tradingValue"), "source": "네이버", "updatedAt": naver.get("updatedAt") or kwargs["update_time"]},
            {"label": "표시 거래대금", "raw": kwargs["trading_value"], "converted": kwargs["trading_value"], "source": "네이버 우선 / 없으면 pykrx OHLCV 추정", "updatedAt": kwargs["update_time"]},
            {"label": "추정 거래대금", "raw": kwargs["estimated_trading_value"], "converted": kwargs["estimated_trading_value"], "source": "pykrx OHLCV ((시가+고가+저가+종가)/4*거래량)", "updatedAt": kwargs["latest_date"].strftime("%Y-%m-%d")},
            {"label": "MA5", "raw": ma.get("ma5"), "converted": ma.get("ma5"), "source": "pykrx(KRX 일봉 종가)", "updatedAt": kwargs["latest_date"].strftime("%Y-%m-%d")},
            {"label": "MA20", "raw": ma.get("ma20"), "converted": ma.get("ma20"), "source": "pykrx(KRX 일봉 종가)", "updatedAt": kwargs["latest_date"].strftime("%Y-%m-%d")},
            {"label": "MA60", "raw": ma.get("ma60"), "converted": ma.get("ma60"), "source": "pykrx(KRX 일봉 종가)", "updatedAt": kwargs["latest_date"].strftime("%Y-%m-%d")},
            {"label": "MA120", "raw": ma.get("ma120"), "converted": ma.get("ma120"), "source": "pykrx(KRX 일봉 종가)", "updatedAt": kwargs["latest_date"].strftime("%Y-%m-%d")},
        ],
        "notice": "장중 현재가/거래량/거래대금은 잠정 데이터입니다. 이동평균선은 장중 현재가를 넣지 않고 pykrx KRX 일봉 종가 기준으로 계산합니다.",
        "quoteMode": kwargs["quote_mode"],
        "isIntraday": kwargs["is_intraday"],
    }


def is_market_hours(now):
    if now.weekday() >= 5:
        return False
    start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return start <= now <= end


def moving_average(series, days):
    if len(series) < days:
        return None
    return to_number(series.tail(days).mean())


def estimate_trading_value(open_price, high, low, close, volume):
    if None in [open_price, high, low, close, volume]:
        return None
    return to_number(((open_price + high + low + close) / 4) * volume)


def interpret_volume_ratio(ratio):
    if ratio is None:
        return "데이터 없음"
    if ratio < 1.0:
        return "평균 이하"
    if ratio < 1.3:
        return "평균 수준"
    if ratio < 2.0:
        return "관심 증가"
    if ratio < 4.0:
        return "강한 수급"
    return "폭발적 거래량"


def interpret_breakout(close, prior60_high):
    if close is None or prior60_high is None:
        return "데이터 없음"
    if close > prior60_high:
        return "전고점 돌파"
    if close >= prior60_high * 0.97:
        return "전고점 근처"
    return "아직 돌파 전"


def pct_from(current, reference):
    if current is None or not reference:
        return None
    return (current / reference - 1) * 100


def compare_gt(left, right):
    if left is None or right is None:
        return None
    return left > right


def all_not_none(values):
    return all(value is not None for value in values)


def normalize_name(value):
    return (value or "").replace(" ", "").lower()


def to_number(value):
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
        return int(round(float(value)))
    except Exception:
        return None


def to_float(value):
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    except Exception:
        return None


def fmt(value):
    if isinstance(value, dt.datetime):
        value = value.date()
    return value.strftime("%Y%m%d")


def format_won(value):
    if value is None:
        return "데이터 없음"
    return f"{int(value):,}원"


def format_qty(value):
    if value is None:
        return "데이터 없음"
    return f"{int(value):,}주"


def format_percent(value):
    if value is None:
        return "데이터 없음"
    return f"{value:.2f}%"


def format_multiple(value):
    if value is None:
        return "데이터 없음"
    return f"{value:.2f}배"


def format_eok(value):
    if value is None:
        return "데이터 없음"
    sign = "+" if value > 0 else ""
    return f"{sign}{round(value / 100000000):,}억"


def format_big_money(value):
    if value is None:
        return "데이터 없음"
    eok = value / 100000000
    if abs(eok) >= 1000:
        return f"{eok / 1000:.2f}천억 원"
    return f"{eok:.0f}억 원"


def format_rank(value):
    if value is None:
        return "데이터 없음"
    return f"{value}위"
