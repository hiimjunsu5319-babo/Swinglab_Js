import datetime as dt
import hashlib
import json
import math
import random
import urllib.error
import urllib.request


REQUIRED_FIELDS = {
    "currentPrice",
    "changeRate",
    "volume",
    "tradingValue",
    "foreignNet",
    "institutionNet",
    "individualNet",
    "history",
}


def fetch_market_data(holding, source_url=""):
    if source_url:
        data = fetch_from_json_api(holding, source_url)
        if data:
            return normalize_api_data(data, source_url)
    return demo_market_data(holding)


def fetch_from_json_api(holding, source_url):
    url = source_url.replace("{code}", holding["code"]).replace("{name}", holding["name"])
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "PortfolioSignalMVP/0.1 (+personal analysis tool)",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            if response.status >= 400:
                return None
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None


def normalize_api_data(data, source_url):
    if not REQUIRED_FIELDS.issubset(data.keys()):
        return None
    data["source"] = data.get("source", "사용자 설정 API")
    data["sourceUrl"] = data.get("sourceUrl", source_url)
    return data


def demo_market_data(holding):
    seed_text = f"{holding['code']}:{dt.date.today().isoformat()}"
    seed = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:12], 16)
    rng = random.Random(seed)

    avg_price = float(holding["avg_price"])
    base = max(avg_price * rng.uniform(0.86, 1.22), 500)
    history = []
    close = base * rng.uniform(0.92, 1.05)

    for days_ago in range(130, -1, -1):
        day = dt.date.today() - dt.timedelta(days=days_ago)
        drift = math.sin(days_ago / 9) * 0.008 + rng.uniform(-0.025, 0.026)
        close = max(close * (1 + drift), 100)
        volume = int(rng.uniform(80_000, 2_400_000))
        trading_value = int(volume * close)
        foreign = int(rng.uniform(-80_000, 110_000))
        institution = int(rng.uniform(-70_000, 90_000))
        individual = -(foreign + institution) + int(rng.uniform(-10_000, 10_000))
        history.append(
            {
                "date": day.isoformat(),
                "close": round(close, 0),
                "volume": volume,
                "tradingValue": trading_value,
                "foreignNet": foreign,
                "institutionNet": institution,
                "individualNet": individual,
            }
        )

    today = history[-1]
    yesterday = history[-2]
    change_rate = ((today["close"] - yesterday["close"]) / yesterday["close"]) * 100

    return {
        "currentPrice": today["close"],
        "changeRate": round(change_rate, 2),
        "volume": today["volume"],
        "tradingValue": today["tradingValue"],
        "foreignNet": today["foreignNet"],
        "institutionNet": today["institutionNet"],
        "individualNet": today["individualNet"],
        "history": history,
        "source": "MVP 데모 데이터",
        "sourceUrl": "collector.py demo provider",
    }
