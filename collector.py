import datetime as dt


def moving_average(history, days):
    closes = [item["close"] for item in history[-days:]]
    if not closes:
        return 0
    return round(sum(closes) / len(closes), 2)


def sum_flow(history, key, days):
    return sum(item.get(key, 0) for item in history[-days:])


def avg_value(history, key, days):
    rows = history[-days:]
    if not rows:
        return 0
    return sum(item.get(key, 0) for item in rows) / len(rows)


def build_report(holding, market_data):
    history = market_data["history"]
    current = float(market_data["currentPrice"])
    avg_price = float(holding["avg_price"])
    quantity = int(holding["quantity"])
    profit_rate = ((current - avg_price) / avg_price) * 100 if avg_price else 0

    ma = {
        "ma5": moving_average(history, 5),
        "ma20": moving_average(history, 20),
        "ma60": moving_average(history, 60),
        "ma120": moving_average(history, 120),
    }
    if ma["ma5"] > ma["ma20"] > ma["ma60"] > ma["ma120"]:
        ma_state = "정배열"
    elif ma["ma5"] < ma["ma20"] < ma["ma60"] < ma["ma120"]:
        ma_state = "역배열"
    else:
        ma_state = "혼조"

    flow5 = {
        "foreign": sum_flow(history, "foreignNet", 5),
        "institution": sum_flow(history, "institutionNet", 5),
        "individual": sum_flow(history, "individualNet", 5),
    }
    flow20 = {
        "foreign": sum_flow(history, "foreignNet", 20),
        "institution": sum_flow(history, "institutionNet", 20),
        "individual": sum_flow(history, "individualNet", 20),
    }

    avg_volume20 = avg_value(history[:-1], "volume", 20)
    avg_trading_value20 = avg_value(history[:-1], "tradingValue", 20)
    volume_ratio = market_data["volume"] / avg_volume20 if avg_volume20 else 1
    value_ratio = market_data["tradingValue"] / avg_trading_value20 if avg_trading_value20 else 1

    closes20 = [item["close"] for item in history[-20:]]
    previous_high = max(closes20)
    previous_low = min(closes20)
    support = min(previous_low, ma["ma20"])
    resistance1 = max(previous_high, ma["ma20"])
    resistance2 = resistance1 * 1.08
    stop_loss = min(avg_price * 0.92, support * 0.98)

    supply_ok = flow5["foreign"] + flow5["institution"] > 0
    activity_up = volume_ratio >= 1.25 or value_ratio >= 1.25

    score = 0
    score += 2 if ma_state == "정배열" else -2 if ma_state == "역배열" else 0
    score += 1 if supply_ok else -1
    score += 1 if profit_rate >= 0 else -1
    score += 1 if activity_up and market_data["changeRate"] > 0 else 0
    score -= 1 if profit_rate <= -8 else 0

    if score >= 2:
        signal = "보유 우세"
    elif score <= -2:
        signal = "매도 검토"
    else:
        signal = "주의"

    buy_reason = holding.get("buy_reason") or ""
    checklist = [
        {
            "label": "매수 이유가 가격 흐름과 충돌하지 않음",
            "passed": profit_rate > -8 and ma_state != "역배열",
        },
        {
            "label": "외국인/기관 5일 합산 수급이 유지됨",
            "passed": supply_ok,
        },
        {
            "label": "거래량 또는 거래대금이 20일 평균 대비 증가",
            "passed": activity_up,
        },
        {
            "label": "직접 입력한 매수 이유가 남아 있음",
            "passed": len(buy_reason.strip()) > 0,
        },
    ]

    return {
        "holdingId": holding["id"],
        "name": holding["name"],
        "code": holding["code"],
        "reportDate": dt.date.today().isoformat(),
        "createdAt": dt.datetime.now().isoformat(timespec="seconds"),
        "signal": signal,
        "source": market_data.get("source", "unknown"),
        "sourceUrl": market_data.get("sourceUrl", ""),
        "updatedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "market": {
            "currentPrice": round(current, 0),
            "changeRate": market_data["changeRate"],
            "volume": market_data["volume"],
            "tradingValue": market_data["tradingValue"],
            "foreignNet": market_data["foreignNet"],
            "institutionNet": market_data["institutionNet"],
            "individualNet": market_data["individualNet"],
            "holdingValue": round(current * quantity, 0),
            "profitRate": round(profit_rate, 2),
            "profitAmount": round((current - avg_price) * quantity, 0),
        },
        "flow5": flow5,
        "flow20": flow20,
        "movingAverages": ma,
        "maState": ma_state,
        "levels": {
            "previousHigh": round(previous_high, 0),
            "previousLow": round(previous_low, 0),
            "support": round(support, 0),
            "stopLoss": round(stop_loss, 0),
            "resistance1": round(resistance1, 0),
            "resistance2": round(resistance2, 0),
        },
        "activity": {
            "volumeRatio20": round(volume_ratio, 2),
            "tradingValueRatio20": round(value_ratio, 2),
            "isIncreased": activity_up,
        },
        "summary": make_summary(signal, ma_state, supply_ok, activity_up, profit_rate),
        "checklist": checklist,
        "history": history[-30:],
    }


def make_summary(signal, ma_state, supply_ok, activity_up, profit_rate):
    supply_text = "외국인·기관 합산 수급은 유지되는 편" if supply_ok else "외국인·기관 합산 수급은 약한 편"
    activity_text = "거래 활동은 평균 대비 커졌습니다" if activity_up else "거래 활동은 평균 범위에 있습니다"
    return (
        f"{signal} 신호입니다. 이동평균선은 {ma_state} 상태이고, "
        f"{supply_text}입니다. {activity_text}. "
        f"평균단가 기준 수익률은 {profit_rate:.2f}%입니다."
    )
