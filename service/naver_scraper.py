# -*- coding: utf-8 -*-
import html
import json
import base64
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE = "https://finance.naver.com"
CAPTURE_DIR = Path(os.environ.get("NAVER_CAPTURE_DIR", "static/naver_captures"))
NAVER_CAPTURE_WIDTH = 1100
NAVER_CAPTURE_HEIGHT = 1000
NAVER_CAPTURE_SCALE = 2
NAVER_CAPTURE_TOP_CROP = 220
CAPTURE_MAX_AGE_SECONDS = 24 * 60 * 60
CAPTURE_MAX_FILES = 200
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def capture_url(filename):
    try:
        relative = CAPTURE_DIR.resolve().relative_to(Path("static").resolve())
        return "/" + str(relative / filename).replace("\\", "/")
    except ValueError:
        return f"/naver_captures/{filename}"


def fetch_naver_snapshot(ticker, include_image=True, include_rank=True):
    result = {
        "available": False,
        "error": "",
        "updatedAt": "",
        "currentPrice": None,
        "volume": None,
        "marketCap": None,
        "foreignHoldingRate": None,
        "tradingValue": None,
        "rawTradingValueText": "",
        "tradingValueRank": None,
        "marketInterest": "데이터 없음",
        "flow": {
            "foreign5": None,
            "foreign20": None,
            "institution5": None,
            "institution20": None,
            "individual5": None,
            "individual20": None,
            "jointStatus": "네이버 금융 데이터를 가져올 수 없습니다.",
            "available": False,
        },
        "flowRows": [],
        "flowImageUrl": "",
        "summaryImageUrl": "",
    }
    try:
        main_html = fetch_html(f"{BASE}/item/main.naver?code={ticker}")
        result.update(parse_main_page(main_html))
        result["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")

        flow_rows = fetch_investor_rows(ticker)
        result["flowRows"] = flow_rows
        if flow_rows:
            flow = summarize_flow(flow_rows)
            result["flow"] = flow
            result["foreignHoldingRate"] = flow_rows[0].get("foreignRate") or result["foreignHoldingRate"]
            if include_image:
                result["flowImageUrl"] = render_flow_image(ticker, flow_rows)

        if include_rank:
            rank = fetch_trading_value_rank(ticker)
            result["tradingValueRank"] = rank
            result["marketInterest"] = interpret_market_interest(rank)
        result["available"] = True
    except Exception as exc:
        result["error"] = f"네이버 금융 데이터를 가져올 수 없습니다. {exc}"
    return result


def resolve_ticker_from_naver_code(ticker):
    try:
        body = fetch_html(f"{BASE}/item/main.naver?code={ticker}")
        text = strip_tags(body)
        code_match = re.search(r"종목코드\s*(\d{6})\s*(코스피|코스닥)", text)
        name_match = re.search(r"종목명\s+(.+?)\s+종목코드", text)
        if not name_match:
            name_match = re.search(r"<h2><a[^>]*>(.*?)</a>", body, re.DOTALL)
        if not code_match and ticker not in body:
            return None
        name = clean_cell(name_match.group(1)) if name_match else ticker
        market_text = code_match.group(2) if code_match else ""
        market = "KOSPI" if "코스피" in market_text else "KOSDAQ" if "코스닥" in market_text else ""
        return {"ticker": ticker, "name": name, "market": market}
    except Exception:
        return None


def search_tickers_from_naver(query):
    url = (
        "https://ac.finance.naver.com/ac?"
        + urllib.parse.urlencode({"q": query, "target": "stock,ipo,index,marketindicator"})
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.naver.com/search/search.naver",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        body = response.read().decode("utf-8", errors="ignore")
    return parse_naver_autocomplete(body)


def parse_naver_autocomplete(body):
    body = body.strip()
    if body.startswith("jindo"):
        body = body[body.find("{") : body.rfind("}") + 1]
    data = json.loads(body)
    candidates = []

    def walk(value):
        if isinstance(value, dict):
            ticker = first_value(value, ["code", "ticker", "itemCode", "symbol"])
            name = first_value(value, ["name", "itemName", "korName", "txt"])
            market = first_value(value, ["market", "type"])
            link = first_value(value, ["link", "url"])
            if not ticker and link:
                match = re.search(r"code=(\d{6})|/stock/(\d{6})", str(link))
                if match:
                    ticker = match.group(1) or match.group(2)
            if ticker and re.fullmatch(r"\d{6}", str(ticker)):
                candidates.append(
                    {
                        "ticker": str(ticker),
                        "name": clean_cell(str(name or ticker)),
                        "market": normalize_market_text(str(market or "")),
                        "source": "naver_fallback",
                    }
                )
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            if len(value) >= 2:
                text = " ".join(clean_cell(str(item)) for item in value)
                code_match = re.search(r"\b(\d{6})\b", text)
                if code_match:
                    ticker = code_match.group(1)
                    name = ""
                    for item in value:
                        cell = clean_cell(str(item))
                        if cell and not re.fullmatch(r"\d{6}", cell) and "http" not in cell and "KOS" not in cell.upper():
                            name = re.sub(r"<[^>]+>", "", cell)
                            break
                    candidates.append(
                        {
                            "ticker": ticker,
                            "name": name or ticker,
                            "market": normalize_market_text(text),
                            "source": "naver_fallback",
                        }
                    )
            for child in value:
                walk(child)

    walk(data)
    unique = {}
    for item in candidates:
        unique[item["ticker"]] = item
    return list(unique.values())


def first_value(mapping, keys):
    for key in keys:
        if key in mapping and mapping[key]:
            return mapping[key]
    return None


def normalize_market_text(value):
    text = value.upper()
    if "KOSPI" in text or "코스피" in value:
        return "KOSPI"
    if "KOSDAQ" in text or "코스닥" in value:
        return "KOSDAQ"
    return "UNKNOWN"


def fetch_deal_rankings(limit=10):
    foreign = fetch_deal_ranking_group("9000", "buy")
    institution = fetch_deal_ranking_group("1000", "buy")
    foreign_sell = fetch_deal_ranking_group("9000", "sell")
    institution_sell = fetch_deal_ranking_group("1000", "sell")
    combined = combine_deal_rankings(foreign, institution)
    combined_sell = sorted(
        combine_deal_rankings(foreign_sell, institution_sell),
        key=lambda item: abs(item.get("amount", 0)),
        reverse=True,
    )
    return {
        "foreign": foreign[:limit],
        "institution": institution[:limit],
        "combined": combined[:limit],
        "foreignSell": foreign_sell[:limit],
        "institutionSell": institution_sell[:limit],
        "combinedSell": combined_sell[:limit],
    }


def fetch_deal_ranking_group(investor_gubun, deal_type="buy"):
    rows = []
    for sosok, market in [("01", "KOSPI"), ("02", "KOSDAQ")]:
        url = f"{BASE}/sise/sise_deal_rank_iframe.naver?sosok={sosok}&investor_gubun={investor_gubun}&type={deal_type}"
        try:
            body = fetch_html(url)
            rows.extend(parse_deal_rank_iframe(body, market, investor_gubun))
        except Exception:
            continue
    return sorted(rows, key=lambda item: item.get("amount", 0), reverse=True)


def parse_deal_rank_iframe(body, market, investor_gubun):
    rows = []
    rank = 0
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.DOTALL):
        code_match = re.search(r"code=(\d{6})", tr)
        name_match = re.search(r'class="(?:company|tltle)"[^>]*>(.*?)</a>', tr, re.DOTALL)
        if not code_match or not name_match:
            continue
        cells = [clean_cell(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)]
        numbers = [parse_int(cell) for cell in cells if re.search(r"[-+]?\d", cell)]
        rank += 1
        rows.append(
            {
                "rank": rank,
                "ticker": code_match.group(1),
                "name": clean_cell(name_match.group(1)),
                "market": market,
                "investor": "foreign" if investor_gubun == "9000" else "institution",
                "quantity": numbers[-3] if len(numbers) >= 3 else None,
                "amount": (numbers[-2] if len(numbers) >= 2 else 0) * 1000000,
                "dayVolume": numbers[-1] if numbers else None,
            }
        )
    return rows


def combine_deal_rankings(foreign, institution):
    by_ticker = {}
    for source, label in [(foreign, "foreign"), (institution, "institution")]:
        for item in source:
            ticker = item["ticker"]
            target = by_ticker.setdefault(
                ticker,
                {
                    "ticker": ticker,
                    "name": item["name"],
                    "market": item["market"],
                    "foreignAmount": 0,
                    "institutionAmount": 0,
                    "amount": 0,
                },
            )
            value = item.get("amount") or 0
            if label == "foreign":
                target["foreignAmount"] += value
            else:
                target["institutionAmount"] += value
            target["amount"] += value
    return sorted(by_ticker.values(), key=lambda item: item["amount"], reverse=True)


def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as response:
        data = response.read()
    candidates = []
    for encoding in ["utf-8", "cp949", "euc-kr"]:
        try:
            text = data.decode(encoding)
            score = sum(text.count(word) for word in ["삼성", "시가총액", "외국인", "기관", "거래대금", "날짜"])
            candidates.append((score, text))
        except UnicodeDecodeError:
            continue
    if candidates:
        return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]
    return data.decode("utf-8", errors="ignore")


def parse_main_page(body):
    text = strip_tags(body)
    compact = re.sub(r"\s+", " ", text)
    quote = parse_nxt_quote(body) or {}
    current_price = quote.get("currentPrice")
    volume = quote.get("volume")
    market_cap = None
    foreign_rate = None
    trading_value = quote.get("tradingValue")
    raw_trading_value_text = quote.get("rawTradingValueText") or ""
    raw_volume_text = quote.get("rawVolumeText") or ""
    quote_source_detail = quote.get("quoteSourceDetail") or "네이버 KRX"

    price_match = re.search(r"(?:현재가|종가)\s*([\d,]+)", compact)
    if current_price is None and price_match:
        current_price = parse_int(price_match.group(1))

    volume_match = re.search(r"거래량\s*([\d,]+)", compact)
    if volume is None and volume_match:
        volume = parse_int(volume_match.group(1))
        raw_volume_text = volume_match.group(1)

    cap_large_match = re.search(r"시가총액\s+시가총액\s+([\d,]+)조\s+([\d,]+)\s*억원", text)
    if not cap_large_match:
        cap_large_match = re.search(r"시가총액\s+([\d,]+)조\s+([\d,]+)\s*억원", text)
    if cap_large_match:
        market_cap = parse_int(cap_large_match.group(1)) * 1000000000000 + parse_int(cap_large_match.group(2)) * 100000000
    else:
        cap_match = re.search(r"시가총액\s*([\d,]+)\s*억원", text)
        if cap_match:
            market_cap = parse_int(cap_match.group(1)) * 100000000

    if market_cap is None:
        cap_table_match = re.search(r"시가총액\(억\)\s*([\d,]+)", text)
        if cap_table_match:
            market_cap = parse_int(cap_table_match.group(1)) * 100000000

    foreign_match = re.search(r"외국인소진율\s*([\d.]+)%", text)
    if foreign_match:
        foreign_rate = parse_float(foreign_match.group(1))

    value_match = re.search(r"거래대금\s*([\d,]+)\s*백만", compact)
    if trading_value is None and value_match:
        raw_trading_value_text = f"{value_match.group(1)}백만 원"
        trading_value = parse_int(value_match.group(1)) * 1000000

    return {
        "currentPrice": current_price,
        "volume": volume,
        "rawVolumeText": raw_volume_text,
        "marketCap": market_cap,
        "foreignHoldingRate": foreign_rate,
        "tradingValue": trading_value,
        "rawTradingValueText": raw_trading_value_text,
        "quoteSourceDetail": quote_source_detail,
    }


def parse_nxt_quote(body):
    """Prefer the NXT quote table when Naver exposes both KRX and NXT values."""
    match = re.search(
        r'<div class="rate_info"\s+id="rate_info_nxt"[^>]*>(.*?)(?=<div class="chart")',
        body,
        re.DOTALL,
    )
    if not match:
        return None

    section = match.group(1)
    compact = strip_tags(section)
    price_match = re.search(r"오늘의시세\s*([\d,]+)", compact)
    if not price_match:
        price_match = re.search(r'<p class="no_today".*?<span class="blind">([\d,]+)</span>', section, re.DOTALL)
    volume_match = re.search(r"거래량\s*([\d,]+)", compact)
    value_match = re.search(r"거래대금\s*([\d,]+)\s*백만", compact)
    if not value_match:
        value_match = re.search(
            r'sp_txt10">거래대금</span>.*?<span class="blind">([\d,]+)</span>.*?sp_txt11">백만</span>',
            section,
            re.DOTALL,
        )

    if not any([price_match, volume_match, value_match]):
        return None

    trading_value = None
    raw_trading_value_text = ""
    if value_match:
        raw_trading_value_text = f"{value_match.group(1)}백만 원"
        trading_value = parse_int(value_match.group(1)) * 1000000

    return {
        "currentPrice": parse_int(price_match.group(1)) if price_match else None,
        "volume": parse_int(volume_match.group(1)) if volume_match else None,
        "rawVolumeText": volume_match.group(1) if volume_match else "",
        "tradingValue": trading_value,
        "rawTradingValueText": raw_trading_value_text,
        "quoteSourceDetail": "네이버 NXT",
    }


def fetch_investor_rows(ticker, pages=2):
    rows = []
    for page in range(1, pages + 1):
        body = fetch_html(f"{BASE}/item/frgn.naver?code={ticker}&page={page}")
        table = find_table(body, "외국인 기관 순매매 거래량")
        if not table:
            continue
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.DOTALL):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
            if len(cells) < 9:
                continue
            values = [clean_cell(cell) for cell in cells]
            if not re.match(r"\d{4}\.\d{2}\.\d{2}", values[0]):
                continue
            close = parse_int(values[1])
            institution_volume = parse_int(values[5])
            foreign_volume = parse_int(values[6])
            individual_volume = -(institution_volume + foreign_volume)
            rows.append(
                {
                    "date": values[0],
                    "close": close,
                    "change": values[2],
                    "changeRate": values[3],
                    "volume": parse_int(values[4]),
                    "institutionVolume": institution_volume,
                    "foreignVolume": foreign_volume,
                    "individualVolume": individual_volume,
                    "institutionValue": institution_volume * close,
                    "foreignValue": foreign_volume * close,
                    "individualValue": individual_volume * close,
                    "foreignHolding": parse_int(values[7]),
                    "foreignRate": parse_float(values[8].replace("%", "")),
                }
            )
    return rows


def summarize_flow(rows):
    foreign5 = sum(row["foreignValue"] for row in rows[:5])
    foreign20 = sum(row["foreignValue"] for row in rows[:20])
    institution5 = sum(row["institutionValue"] for row in rows[:5])
    institution20 = sum(row["institutionValue"] for row in rows[:20])
    individual5 = sum(row["individualValue"] for row in rows[:5])
    individual20 = sum(row["individualValue"] for row in rows[:20])
    return {
        "foreign5": foreign5,
        "foreign20": foreign20,
        "institution5": institution5,
        "institution20": institution20,
        "individual5": individual5,
        "individual20": individual20,
        "jointStatus": interpret_flow(foreign20, institution20),
        "available": True,
    }


def fetch_trading_value_rank(ticker):
    # Naver's ranking pages change often. Try market pages that expose 거래대금;
    # if the ticker is not found, return None and keep the site running.
    for sosok in ["0", "1"]:
        for path in [
            f"/sise/sise_market_sum.naver?sosok={sosok}",
            f"/sise/sise_quant.naver?sosok={sosok}",
            f"/sise/sise_rise.naver?sosok={sosok}",
        ]:
            try:
                body = fetch_html(BASE + path)
                rank = find_rank_in_table(body, ticker)
                if rank:
                    return rank
            except Exception:
                continue
    return None


def find_rank_in_table(body, ticker):
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.DOTALL)
    rank = 0
    for tr in rows:
        if f"code={ticker}" not in tr:
            continue
        rank += 1
        rank_text = clean_cell(tr)
        match = re.search(r"^\s*(\d+)", rank_text)
        if match:
            return parse_int(match.group(1))
        return rank or None
    return None


def render_flow_image(ticker, rows):
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{ticker}-flow-{int(time.time())}.png"
    path = CAPTURE_DIR / filename

    width, height = 920, 760
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font_title = load_font(20, bold=True)
    font_header = load_font(16)
    font_cell = load_font(15)

    draw.text((42, 10), "외국인 · 기관 순매매 거래량", fill="#ff5a00", font=font_title)
    headers = ["날짜", "종가", "전일비", "등락률", "거래량", "기관 순매매량", "외국인 순매매량", "보유주수", "보유율"]
    col_x = [42, 135, 230, 330, 424, 515, 625, 725, 835]
    col_w = [75, 90, 90, 80, 90, 105, 105, 105, 55]

    draw.rectangle((42, 30, 892, 84), fill="#eeeeee")
    for x, w, header in zip(col_x, col_w, headers):
        draw.text((x + 6, 54), header, fill="#666666", font=font_header)
        draw.line((x, 30, x, 84), fill="#dddddd")
    draw.line((892, 30, 892, 84), fill="#dddddd")

    y = 104
    for index, row in enumerate(rows[:20]):
        if index and index % 5 == 0:
            draw.line((42, y - 13, 892, y - 13), fill="#dddddd")
        values = [
            row["date"],
            f"{row['close']:,}",
            row["change"],
            row["changeRate"],
            f"{row['volume']:,}",
            signed(row["institutionVolume"]),
            signed(row["foreignVolume"]),
            f"{row['foreignHolding']:,}",
            f"{row['foreignRate']:.2f}%" if row["foreignRate"] is not None else "-",
        ]
        colors = [
            "#777777",
            "#111111",
            color_by_text(row["change"]),
            color_by_text(row["changeRate"]),
            "#111111",
            color_by_value(row["institutionVolume"]),
            color_by_value(row["foreignVolume"]),
            "#1f2d3d",
            "#1f2d3d",
        ]
        for x, value, color in zip(col_x, values, colors):
            draw.text((x + 6, y), value, fill=color, font=font_cell)
        y += 34

    image.save(path)
    cleanup_capture_dir()
    return capture_url(filename)


def render_summary_image(result, chart_rows, flow_rows):
    return capture_naver_page_screenshot(result.get("ticker"), result.get("quoteMode", "NAVER"))
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    ticker = result.get("ticker", "stock")
    filename = f"{ticker}-summary-{int(time.time())}.png"
    path = CAPTURE_DIR / filename

    width, height = 1000, 820
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font_title = load_font(22, bold=True)
    font_bold = load_font(15, bold=True)
    font_cell = load_font(14)
    font_small = load_font(12)
    font_price = load_font(34, bold=True)

    basic = result.get("basic", {})
    trading = result.get("tradingValueAnalysis", {})
    ma = result.get("movingAverage", {})
    flow = result.get("flow", {})

    draw.text((26, 12), str(result.get("name") or ticker), fill="#111111", font=font_title)
    draw.text((174, 18), str(ticker), fill="#555555", font=font_bold)
    draw.rectangle((230, 14, 262, 31), outline="#c8c8c8", fill="#f7f7f7")
    draw.text((236, 16), str(result.get("market") or ""), fill="#555555", font=font_small)
    draw.text((276, 18), f"{result.get('date', '')} 기준", fill="#555555", font=font_small)
    draw.line((22, 42, 982, 42), fill="#5b6470", width=3)

    draw.rectangle((22, 56, 126, 84), outline="#cccccc", fill="#f4f4f4")
    draw.rectangle((126, 56, 232, 84), outline="#cccccc", fill="#ffffff")
    draw.text((67, 62), "KRX", fill="#999999", font=font_bold, anchor="ma")
    draw.text((179, 62), "NXT", fill="#111111", font=font_bold, anchor="ma")
    draw.text((580, 64), "넥스트레이드(NXT)", fill="#666666", font=font_small)

    price = basic.get("currentPrice")
    change = basic.get("changeRate")
    price_color = "#0068ff" if change is not None and change < 0 else "#ff0000" if change and change > 0 else "#111111"
    draw.text((28, 100), f"{price:,}" if price else "-", fill=price_color, font=font_price)
    draw.text((28, 140), f"등락률 {change:+.2f}%" if change is not None else "등락률 -", fill=price_color, font=font_bold)

    info_x = 250
    info_rows = [
        ("전일", basic.get("krxClose")),
        ("고가", basic.get("high")),
        ("거래량", basic.get("volume")),
        ("시가", basic.get("open")),
        ("저가", basic.get("low")),
        ("거래대금", trading.get("tradingValue")),
    ]
    positions = [(info_x, 96), (info_x + 150, 96), (info_x + 335, 96), (info_x, 136), (info_x + 150, 136), (info_x + 335, 136)]
    for (label, value), (x, y) in zip(info_rows, positions):
        draw.text((x, y), label, fill="#666666", font=font_bold)
        text = format_image_money(value) if label == "거래대금" else (f"{int(value):,}" if value else "-")
        value_offset = 82 if label == "거래대금" else 58
        draw.text((x + value_offset, y), text, fill="#111111", font=font_bold)

    side_x = 734
    draw.rectangle((side_x, 56, 972, 300), outline="#d5d5d5", fill="#fbfbfb")
    draw.rectangle((side_x, 56, side_x + 120, 88), outline="#d5d5d5", fill="#ffffff")
    draw.text((side_x + 60, 64), "투자정보", fill="#111111", font=font_bold, anchor="ma")
    side_rows = [
        ("시가총액", format_image_money(basic.get("marketCap"))),
        ("외국인보유율", f"{flow.get('foreignHoldingRate'):.2f}%" if flow.get("foreignHoldingRate") is not None else "-"),
        ("거래대금순위", f"{trading.get('rank')}위" if trading.get("rank") else "-"),
        ("MA5", f"{int(ma.get('ma5')):,}" if ma.get("ma5") else "-"),
        ("MA20", f"{int(ma.get('ma20')):,}" if ma.get("ma20") else "-"),
        ("MA60", f"{int(ma.get('ma60')):,}" if ma.get("ma60") else "-"),
    ]
    y = 104
    for label, value in side_rows:
        draw.text((side_x + 16, y), label, fill="#333333", font=font_cell)
        draw.text((side_x + 220, y), value, fill="#111111", font=font_cell, anchor="ra")
        y += 26

    draw.rectangle((22, 176, 722, 486), outline="#ccd3da", fill="#ffffff")
    draw.text((30, 188), "한국거래소(KRX) / pykrx 차트", fill="#777777", font=font_small)
    draw_chart(draw, chart_rows, (30, 216, 700, 450), font_small)
    draw_ma_legend(draw, ma, 30, 456, font_small)

    draw.line((22, 528, 982, 528), fill="#555555", width=2)
    tabs = ["종합정보", "시세", "차트", "투자자별 매매동향", "뉴스공시", "공매도현황"]
    x = 22
    for index, tab in enumerate(tabs):
        w = 74 if index < 3 else 150
        fill = "#4264a9" if index == 0 else "#ffffff"
        text_fill = "#ffffff" if index == 0 else "#111111"
        draw.rectangle((x, 562, x + w, 602), outline="#c9c9c9", fill=fill)
        draw.text((x + w / 2, 574), tab, fill=text_fill, font=font_bold if index == 0 else font_cell, anchor="ma")
        x += w

    draw.text((28, 622), "투자자별 매매동향", fill="#111111", font=font_bold)
    draw.text((145, 624), "거래원 정보 · 일별 상위 5개 거래원의 누적 정보 기준", fill="#666666", font=font_small)
    draw_flow_preview(draw, flow_rows[:5], 28, 650, font_cell, font_small)

    image.save(path)
    return capture_url(filename)


def capture_naver_page_screenshot(ticker, quote_mode="NAVER"):
    if not ticker:
        return ""
    cdp = capture_naver_page_screenshot_cdp(ticker, quote_mode)
    if cdp:
        return cdp
    chrome = find_chrome()
    if not chrome:
        return ""
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{ticker}-naver-page-{int(time.time())}.png"
    path = (CAPTURE_DIR / filename).resolve()
    url = f"{BASE}/item/main.naver?code={ticker}"
    args = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-popup-blocking",
        f"--force-device-scale-factor={NAVER_CAPTURE_SCALE}",
        f"--window-size={NAVER_CAPTURE_WIDTH},{NAVER_CAPTURE_HEIGHT}",
        "--virtual-time-budget=3000",
        f"--screenshot={path}",
        url,
    ]
    try:
        subprocess.run(args, check=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return ""
    if path.exists() and path.stat().st_size > 0:
        crop_naver_capture(path)
        cleanup_capture_dir()
        return capture_url(filename)
    return ""


def capture_naver_page_screenshot_cdp(ticker, quote_mode="NAVER"):
    chrome = find_chrome()
    if not chrome:
        return ""
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{ticker}-naver-page-{int(time.time())}.png"
    path = (CAPTURE_DIR / filename).resolve()
    port = find_free_port()
    profile_dir = tempfile.mkdtemp(prefix="naver-capture-")
    process = None
    try:
        process = subprocess.Popen(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--disable-popup-blocking",
                f"--force-device-scale-factor={NAVER_CAPTURE_SCALE}",
                f"--window-size={NAVER_CAPTURE_WIDTH},{NAVER_CAPTURE_HEIGHT}",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile_dir}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ws_url = wait_for_websocket_url(port)
        if not ws_url:
            return ""
        ws = DevToolsWebSocket(ws_url)
        ws.command("Page.enable")
        ws.command("Runtime.enable")
        ws.command(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": NAVER_CAPTURE_WIDTH,
                "height": NAVER_CAPTURE_HEIGHT,
                "deviceScaleFactor": NAVER_CAPTURE_SCALE,
                "mobile": False,
            },
        )
        ws.command("Page.navigate", {"url": f"{BASE}/item/main.naver?code={ticker}"})
        time.sleep(3)
        tab_text = "KRX" if str(quote_mode).upper() == "KRX" else "NXT"
        click_x = 122 if tab_text == "KRX" else 226
        click_y = 292
        ws.command(
            "Runtime.evaluate",
            {
                "expression": f"""
                (() => {{
                  const wanted = {json.dumps(tab_text)};
                  const nodes = Array.from(document.querySelectorAll('a, button, span, li, td, div'));
                  const target = nodes.find((el) => (el.textContent || '').trim() === wanted);
                  if (target) (target.closest('a,button,li,td,div') || target).click();
                  window.scrollTo(0, 0);
                  return !!target;
                }})()
                """,
                "awaitPromise": True,
            },
        )
        ws.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": click_x, "y": click_y, "button": "left", "clickCount": 1})
        ws.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": click_x, "y": click_y, "button": "left", "clickCount": 1})
        time.sleep(1)
        ws.command(
            "Runtime.evaluate",
            {
                "expression": """
                (() => {
                  const clickByText = (text) => {
                    const normalize = (value) => (value || '').replace(/\\s+/g, '').trim();
                    const clickableNodes = Array.from(document.querySelectorAll('a, button'));
                    let clickable = clickableNodes.find((el) => normalize(el.textContent) === text);
                    if (!clickable) {
                      const nodes = Array.from(document.querySelectorAll('span, li, td, div'));
                      const target = nodes.find((el) => normalize(el.textContent) === text);
                      clickable = target ? target.closest('a,button') : null;
                    }
                    if (!clickable) return false;
                    clickable.click();
                    return true;
                  };
                  clickByText('봉차트');
                  clickByText('일봉');
                  window.scrollTo(0, 0);
                  return true;
                })()
                """,
                "awaitPromise": True,
            },
        )
        ws.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 584, "y": 407, "button": "left", "clickCount": 1})
        ws.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": 584, "y": 407, "button": "left", "clickCount": 1})
        time.sleep(1.5)
        result = ws.command("Page.captureScreenshot", {"format": "png", "fromSurface": True})
        data = result.get("data")
        if not data:
            return ""
        path.write_bytes(base64.b64decode(data))
        crop_naver_capture(path)
        cleanup_capture_dir()
        return capture_url(filename) if path.exists() and path.stat().st_size > 0 else ""
    except Exception:
        return ""
    finally:
        if process:
            process.terminate()
            try:
                process.wait(timeout=3)
            except Exception:
                process.kill()
        shutil.rmtree(profile_dir, ignore_errors=True)


def crop_naver_capture(path):
    try:
        image = Image.open(path)
        scale = max(1, round(image.width / NAVER_CAPTURE_WIDTH))
        top = min(image.height - 1, int(NAVER_CAPTURE_TOP_CROP * scale))
        cropped = image.crop((0, top, image.width, image.height))
        cropped.save(path)
    except Exception:
        return


def cleanup_capture_dir():
    try:
        if not CAPTURE_DIR.exists():
            return
        now = time.time()
        files = []
        for path in CAPTURE_DIR.glob("*.png"):
            try:
                stat = path.stat()
            except OSError:
                continue
            if now - stat.st_mtime > CAPTURE_MAX_AGE_SECONDS:
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            files.append((stat.st_mtime, path))

        if len(files) <= CAPTURE_MAX_FILES:
            return
        files.sort(key=lambda item: item[0])
        for _, path in files[: len(files) - CAPTURE_MAX_FILES]:
            try:
                path.unlink()
            except OSError:
                pass
    except Exception:
        return


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_websocket_url(port, timeout=8):
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/json"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                targets = json.loads(response.read().decode("utf-8", errors="ignore"))
            for target in targets:
                if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                    return target["webSocketDebuggerUrl"]
        except Exception:
            time.sleep(0.2)
    return ""


class DevToolsWebSocket:
    def __init__(self, ws_url):
        parsed = urllib.parse.urlparse(ws_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 80
        self.path = parsed.path
        self.sock = socket.create_connection((self.host, self.port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = self.sock.recv(4096)
        if b"101" not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError("Chrome DevTools websocket handshake failed")
        self.next_id = 0

    def command(self, method, params=None):
        self.next_id += 1
        message_id = self.next_id
        self.send_json({"id": message_id, "method": method, "params": params or {}})
        while True:
            payload = self.recv_json()
            if payload.get("id") == message_id:
                if "error" in payload:
                    raise RuntimeError(payload["error"])
                return payload.get("result", {})

    def send_json(self, payload):
        data = json.dumps(payload).encode("utf-8")
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.extend([0x80 | 126, (length >> 8) & 255, length & 255])
        else:
            header.append(0x80 | 127)
            header.extend(length.to_bytes(8, "big"))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.sock.sendall(header + masked)

    def recv_json(self):
        while True:
            data = self.recv_frame()
            if data:
                return json.loads(data.decode("utf-8", errors="ignore"))

    def recv_frame(self):
        first = self.read_exact(2)
        opcode = first[0] & 0x0F
        length = first[1] & 0x7F
        if length == 126:
            length = int.from_bytes(self.read_exact(2), "big")
        elif length == 127:
            length = int.from_bytes(self.read_exact(8), "big")
        masked = first[1] & 0x80
        mask = self.read_exact(4) if masked else b""
        payload = self.read_exact(length)
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        if opcode == 0x8:
            raise RuntimeError("websocket closed")
        if opcode == 0x9:
            return b""
        return payload

    def read_exact(self, length):
        chunks = []
        remaining = length
        while remaining:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise RuntimeError("socket closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


def find_chrome():
    for path in CHROME_PATHS:
        if Path(path).exists():
            return path
    return ""


def draw_chart(draw, rows, box, font):
    x1, y1, x2, y2 = box
    if not rows:
        draw.text((x1 + 250, y1 + 90), "차트 데이터 없음", fill="#777777", font=font)
        return
    prices = [row.get("close") for row in rows if row.get("close")]
    volumes = [row.get("volume") for row in rows if row.get("volume")]
    if not prices:
        return
    low, high = min(prices), max(prices)
    span = max(high - low, 1)
    chart_h = 190
    vol_h = 54
    for i in range(6):
        y = y1 + i * chart_h / 5
        draw.line((x1, y, x2, y), fill="#eeeeee")
    for i in range(0, len(rows), max(1, len(rows) // 8)):
        x = x1 + i * (x2 - x1) / max(len(rows) - 1, 1)
        draw.line((x, y1, x, y1 + chart_h + vol_h), fill="#eeeeee")
    points = []
    max_vol = max(volumes) if volumes else 1
    for i, row in enumerate(rows):
        x = x1 + i * (x2 - x1) / max(len(rows) - 1, 1)
        close = row.get("close")
        if close:
            y = y1 + chart_h - ((close - low) / span * chart_h)
            points.append((x, y))
        vol = row.get("volume") or 0
        bar_h = vol / max_vol * vol_h
        draw.rectangle((x - 2, y1 + chart_h + vol_h - bar_h, x + 2, y1 + chart_h + vol_h), fill="#9a85cf")
    if len(points) > 1:
        draw.line(points, fill="#2d6cdf", width=2)
    draw.text((x2 - 70, y1 - 2), f"{int(high):,}", fill="#777777", font=font)
    draw.text((x2 - 70, y1 + chart_h - 10), f"{int(low):,}", fill="#777777", font=font)


def draw_ma_legend(draw, ma, x, y, font):
    colors = [("#2fb344", "5"), ("#e44", "20"), ("#e8a02a", "60"), ("#8c5cc8", "120")]
    draw.text((x, y), "이평선", fill="#777777", font=font)
    offset = 48
    for color, label in colors:
        draw.rectangle((x + offset, y + 4, x + offset + 8, y + 12), fill=color)
        draw.text((x + offset + 12, y), label, fill="#777777", font=font)
        offset += 48


def draw_flow_preview(draw, rows, x, y, font, small_font):
    draw.rectangle((x, y, 702, y + 32), fill="#eeeeee")
    headers = ["날짜", "종가", "외국인", "기관", "보유율"]
    col_x = [x + 12, x + 135, x + 255, x + 385, x + 520]
    for header, cx in zip(headers, col_x):
        draw.text((cx, y + 9), header, fill="#555555", font=small_font)
    y += 42
    for row in rows:
        values = [
            row.get("date", "-"),
            f"{row.get('close', 0):,}" if row.get("close") else "-",
            signed(row.get("foreignVolume", 0)),
            signed(row.get("institutionVolume", 0)),
            f"{row.get('foreignRate'):.2f}%" if row.get("foreignRate") is not None else "-",
        ]
        colors = ["#777777", "#111111", color_by_value(row.get("foreignVolume", 0)), color_by_value(row.get("institutionVolume", 0)), "#111111"]
        for value, color, cx in zip(values, colors, col_x):
            draw.text((cx, y), value, fill=color, font=font)
        y += 28


def format_image_money(value):
    if value is None:
        return "-"
    eok = value / 100000000
    if abs(eok) >= 1000:
        return f"{eok / 1000:.2f}천억"
    return f"{eok:.0f}억"


def find_table(body, caption_text):
    for match in re.finditer(r"<table[^>]*>.*?</table>", body, re.DOTALL):
        table = match.group(0)
        if caption_text in table:
            return table
    return ""


def strip_tags(value):
    return re.sub(r"\s+", " ", clean_cell(value))


def clean_cell(value):
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_int(value):
    match = re.search(r"[-+]?\d[\d,]*", str(value).replace("−", "-"))
    if not match:
        return 0
    return int(match.group(0).replace(",", ""))


def parse_float(value):
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value).replace("−", "-"))
    if not match:
        return None
    return float(match.group(0))


def signed(value):
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,}"


def color_by_value(value):
    if value > 0:
        return "#ff0000"
    if value < 0:
        return "#0068ff"
    return "#111111"


def color_by_text(value):
    text = str(value)
    if "-" in text or "▼" in text:
        return "#0068ff"
    if "+" in text or "▲" in text:
        return "#ff0000"
    return "#111111"


def interpret_flow(foreign20, institution20):
    if foreign20 > 0 and institution20 > 0:
        return "외인+기관 동반 순매수"
    if foreign20 > 0 and institution20 <= 0:
        return "외인만 순매수"
    if institution20 > 0 and foreign20 <= 0:
        return "기관만 순매수"
    return "동반 순매도"


def interpret_market_interest(rank):
    if not rank:
        return "거래대금 순위 데이터를 가져올 수 없습니다."
    if rank <= 10:
        return f"거래대금 순위 {rank}위로 시장 관심이 집중되고 있음"
    if rank <= 50:
        return f"거래대금 순위 {rank}위로 시장 관심이 높은 편"
    return f"거래대금 순위 {rank}위"


def load_font(size, bold=False):
    candidates = [
        r"C:\Windows\Fonts\malgunbd.ttf" if bold else r"C:\Windows\Fonts\malgun.ttf",
        r"C:\Windows\Fonts\malgun.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()
