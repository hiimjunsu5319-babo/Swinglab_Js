import base64
import hashlib
import html
import json
import os
import random
import re
import shutil
import socket
import ssl
import struct
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


CAPTURE_DIR = Path("static") / "captures"
ALPHA_URL = "https://alphasquare.co.kr/home/stock-information?code={code}"


class CaptureError(RuntimeError):
    pass


def normalize_code(query):
    value = (query or "").strip()
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 6:
        return {"code": digits, "name": value if value != digits else ""}
    resolved = resolve_stock_name(value)
    if resolved:
        return resolved
    raise CaptureError("종목코드 6자리로 입력하거나, 네이버 주식 검색에서 찾을 수 있는 정확한 종목명을 입력해 주세요.")


def resolve_stock_name(name):
    if not name:
        return None
    url = "https://m.stock.naver.com/api/search/all?keyword=" + urllib.parse.quote(name)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

    buckets = []
    if isinstance(payload, dict):
        buckets.extend(payload.get("stocks") or [])
        buckets.extend(payload.get("stock") or [])
        buckets.extend(payload.get("items") or [])
        for value in payload.values():
            if isinstance(value, list):
                buckets.extend(value)

    for item in buckets:
        if not isinstance(item, dict):
            continue
        code = str(item.get("reutersCode") or item.get("symbolCode") or item.get("code") or "")
        code = code.split(".")[0].strip()
        stock_name = str(item.get("stockName") or item.get("name") or item.get("korName") or "")
        if len(code) == 6 and code.isdigit():
            return {"code": code, "name": stock_name}
    return None


def capture_stock(query):
    resolved = normalize_code(query)
    code = resolved["code"]
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    browser = find_browser()
    if not browser:
        raise CaptureError("Edge 또는 Chrome 브라우저를 찾지 못했습니다.")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    key = hashlib.sha1(f"{code}-{stamp}-{random.random()}".encode()).hexdigest()[:8]
    output_dir = CAPTURE_DIR / f"{code}-{stamp}-{key}"
    output_dir.mkdir(parents=True, exist_ok=True)

    profile_dir = tempfile.mkdtemp(prefix="alpha-capture-")
    port = free_port()
    process = None
    ws = None
    try:
        url = ALPHA_URL.format(code=code)
        process = subprocess.Popen(
            [
                browser,
                "--headless=new",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile_dir}",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--hide-scrollbars",
                "--window-size=1440,1600",
                url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        page_ws_url = wait_for_page_ws(port)
        ws = CDPClient(page_ws_url)
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        wait_for_page(ws)
        dismiss_popups(ws)

        title = eval_js(ws, "document.title || ''") or f"{code} 종목 정보"
        shots = []

        dismiss_popups(ws)
        shots.append(save_screenshot(ws, output_dir, "01-main", "첫번째 메인화면"))

        click_period(ws, ["주", "주봉", "주간"])
        dismiss_popups(ws)
        shots.append(save_screenshot(ws, output_dir, "02-weekly-chart", "일봉을 주봉으로 바꿔놓은 그래프", chart_clip(ws)))

        dismiss_popups(ws)
        summary_clip = text_clip(ws, ["시가총액", "주식수", "외국인비중"], fallback=right_panel_clip(300, 360))
        shots.append(save_screenshot(ws, output_dir, "03-market-cap-shares", "시총/주식수 요약", summary_clip))

        shots.append(render_investor_trend_image(output_dir, code, 1))
        shots.append(render_investor_trend_image(output_dir, code, 3))

        zip_url = build_zip(output_dir, code, shots)
        return {
            "code": code,
            "name": resolved.get("name") or "",
            "title": title,
            "sourceUrl": url,
            "capturedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "downloadUrl": zip_url,
            "images": shots,
        }
    finally:
        if ws:
            ws.close()
        if process:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        shutil.rmtree(profile_dir, ignore_errors=True)


def build_zip(output_dir, code, shots):
    zip_path = output_dir / f"{code}-alphasquare-captures.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, shot in enumerate(shots, start=1):
            source = output_dir / Path(shot["url"]).name
            archive.write(source, f"{index:02d}-{shot['label']}.png")
    return f"/captures/{output_dir.name}/{zip_path.name}"


def render_investor_trend_image(output_dir, code, months):
    rows = build_investor_trend_rows(code, months)
    image_index = 4 if months == 1 else 5
    filename = f"0{image_index}-investor-net-{months}m.png"
    label = f"투자자별 매매동향 누적 순매수 {months}개월"
    path = output_dir / filename

    width, height = 480, 480
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font_regular = load_font(20)
    font_medium = load_font(22)
    font_bold = load_font(24, bold=True)
    font_small = load_font(18)

    draw.text((14, 24), "투자자별 매매동향", fill="#111111", font=font_bold)
    rounded(draw, (14, 59, 96, 94), 18, "#f0f0f0")
    draw.text((29, 66), "순매수", fill="#111111", font=font_small)
    rounded(draw, (106, 59, 225, 94), 18, "#1f2329")
    draw.text((128, 66), "누적 순매수", fill="white", font=font_small)
    draw.text((378, 68), "차트", fill="#999999", font=font_small)
    rounded(draw, (421, 65, 466, 90), 14, "#e9eaec")
    draw.ellipse((424, 67, 445, 88), fill="white")

    rounded(draw, (39, 111, 439, 145), 5, "#f4f4f4")
    for index, label_text in enumerate(["1개월", "3개월", "6개월", "12개월"]):
        x0 = 39 + index * 100
        if (months == 1 and index == 0) or (months == 3 and index == 1):
            rounded(draw, (x0 + 2, 111, x0 + 98, 145), 5, "white", outline="#e6e6e6")
            fill = "#111111"
            tab_font = font_medium
        else:
            fill = "#999999"
            tab_font = font_regular
        draw.text((x0 + 30, 118), label_text, fill=fill, font=tab_font)

    draw.rectangle((14, 160, 466, 200), fill="#eeeeee")
    for x, title in [(66, "날짜"), (208, "개인"), (323, "기관"), (419, "외인")]:
        draw.text((x, 171), title, fill="#666666", font=font_small)

    y = 214
    for row in rows[:5]:
        draw.text((33, y), row["date"], fill="#666666", font=font_regular)
        draw.text((169, y), format_man(row["individual"]), fill=color_for(row["individual"]), font=font_regular)
        draw.text((280, y), format_man(row["institution"]), fill=color_for(row["institution"]), font=font_regular)
        draw.text((369, y), format_man(row["foreign"]), fill=color_for(row["foreign"]), font=font_regular)
        y += 39

    draw.line((14, 400, 466, 400), fill="#eeeeee", width=1)
    draw.text((58, 419), "‹", fill="#d3d3d3", font=font_bold)
    rounded(draw, (119, 409, 159, 443), 6, "#111111")
    draw.text((134, 416), "1", fill="white", font=font_regular)
    for i, x in enumerate([185, 235, 285, 335], start=2):
        draw.text((x, 419), str(i), fill="#111111", font=font_regular)
    draw.text((409, 416), "›", fill="#111111", font=font_bold)

    if not rows:
        draw.rectangle((14, 210, 466, 360), fill="white")
        draw.text((58, 260), "투자자별 매매동향 데이터를 불러오지 못했습니다.", fill="#666666", font=font_small)

    image.save(path)
    return {"label": label, "url": f"/captures/{output_dir.name}/{filename}"}


def build_investor_trend_rows(code, months):
    raw_rows = fetch_naver_investor_rows(code, pages=8 if months == 3 else 3)
    limit = 63 if months == 3 else 22
    rows = list(reversed(raw_rows[:limit]))
    individual_total = 0
    institution_total = 0
    foreign_total = 0
    cumulative = []
    for row in rows:
        institution_total += row["institution"]
        foreign_total += row["foreign"]
        individual_total += -(row["institution"] + row["foreign"])
        cumulative.append(
            {
                "date": row["date"],
                "individual": individual_total,
                "institution": institution_total,
                "foreign": foreign_total,
            }
        )
    return list(reversed(cumulative))


def fetch_naver_investor_rows(code, pages=8):
    rows = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for page in range(1, pages + 1):
        url = f"https://finance.naver.com/item/frgn.naver?code={code}&page={page}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                body = response.read().decode("cp949", errors="ignore")
        except Exception:
            break
        table = ""
        for match in re.finditer(r'<table[^>]*class="type2"[^>]*>.*?</table>', body, re.DOTALL):
            if "외국인 기관 순매매 거래량" in match.group(0):
                table = match.group(0)
                break
        if not table:
            continue
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.DOTALL):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
            if len(cells) < 7:
                continue
            values = [clean_cell(cell) for cell in cells]
            if not re.match(r"\d{4}\.\d{2}\.\d{2}", values[0]):
                continue
            rows.append(
                {
                    "date": values[0],
                    "institution": parse_int(values[5]),
                    "foreign": parse_int(values[6]),
                }
            )
    return rows


def clean_cell(value):
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_int(value):
    match = re.search(r"[-+]?\d[\d,]*", value.replace("\u2212", "-"))
    if not match:
        return 0
    return int(match.group(0).replace(",", ""))


def format_man(value):
    sign = "+" if value > 0 else ""
    return f"{sign}{round(value / 10000):,}만"


def color_for(value):
    if value > 0:
        return "#ff1111"
    if value < 0:
        return "#0068ff"
    return "#333333"


def load_font(size, bold=False):
    candidates = [
        r"C:\Windows\Fonts\malgunbd.ttf" if bold else r"C:\Windows\Fonts\malgun.ttf",
        r"C:\Windows\Fonts\malgun.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def rounded(draw, box, radius, fill, outline=None):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline)


def find_browser():
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_page_ws(port):
    end = time.time() + 15
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as response:
                pages = json.loads(response.read().decode("utf-8"))
            for page in pages:
                if page.get("type") == "page" and page.get("webSocketDebuggerUrl"):
                    return page["webSocketDebuggerUrl"]
        except Exception:
            time.sleep(0.2)
    raise CaptureError("브라우저 캡처 세션을 시작하지 못했습니다.")


def wait_for_page(ws):
    end = time.time() + 25
    while time.time() < end:
        state = eval_js(ws, "document.readyState")
        body_len = eval_js(ws, "document.body ? document.body.innerText.length : 0") or 0
        if state == "complete" and int(body_len) > 300:
            time.sleep(2)
            return
        time.sleep(0.3)
    raise CaptureError("알파스퀘어 페이지를 불러오는 데 시간이 너무 오래 걸립니다.")


def eval_js(ws, expression):
    result = ws.call(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True},
    )
    remote = result.get("result", {})
    if "value" in remote:
        return remote["value"]
    return None


def click_period(ws, labels):
    click_text(ws, labels, max_text_length=8)
    time.sleep(1.2)


def click_text(ws, labels, max_text_length=40):
    label_js = json.dumps(labels, ensure_ascii=False)
    clicked = eval_js(
        ws,
        f"""
(() => {{
  const labels = {label_js};
  const nodes = [...document.querySelectorAll('button,[role="button"],a,li,span,div')];
  const visible = (el) => {{
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return r.width > 4 && r.height > 4 && r.bottom > 0 && r.right > 0 &&
      r.top < window.innerHeight && style.visibility !== 'hidden' && style.display !== 'none';
  }};
  const node = nodes.find((el) => {{
    if (!visible(el)) return false;
    const text = (el.innerText || el.textContent || '').trim();
    if (!text || text.length > {max_text_length}) return false;
    return labels.some((label) => text === label || text.includes(label));
  }});
  if (node) {{
    node.scrollIntoView({{block:'center', inline:'center'}});
    node.click();
    return true;
  }}
  return false;
}})()
""",
    )
    time.sleep(0.8)
    return bool(clicked)


def dismiss_popups(ws):
    for _ in range(7):
        clicked = eval_js(
            ws,
            """
(() => {
  const hide = (el) => {
    if (!el) return false;
    el.style.setProperty('display', 'none', 'important');
    el.style.setProperty('visibility', 'hidden', 'important');
    return true;
  };
  const labels = ['3일간 보지 않기', '오늘 하루 보지 않기', '닫기', '확인', '×', 'X'];
  const nodes = [...document.querySelectorAll('button,[role="button"],a,span,div')].reverse();
  const node = nodes.find((el) => {
    const text = (el.innerText || el.textContent || '').trim();
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8 || r.bottom < 0 || r.right < 0) return false;
    return labels.some((label) => text === label || text.includes(label));
  });
  if (node) {
    node.click();
    return true;
  }
  const loginWords = ['카카오로 계속하기', '구글로 계속하기', '이메일로 로그인', '이메일로 회원가입'];
  const loginNode = [...document.querySelectorAll('div,section,article,[role="dialog"]')].find((el) => {
    const text = el.innerText || '';
    const r = el.getBoundingClientRect();
    return r.width > 260 && r.height > 220 &&
      r.left > 80 && r.top > 80 &&
      loginWords.some((word) => text.includes(word));
  });
  if (loginNode) {
    const r = loginNode.getBoundingClientRect();
    const closeCandidate = [...document.querySelectorAll('button,a,span,div,svg')].reverse().find((el) => {
      const cr = el.getBoundingClientRect();
      if (cr.width < 8 || cr.height < 8 || cr.width > 60 || cr.height > 60) return false;
      return cr.left > r.right - 70 && cr.right < r.right + 20 && cr.top > r.top - 10 && cr.bottom < r.top + 80;
    });
    if (closeCandidate) {
      closeCandidate.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window}));
      closeCandidate.click?.();
      return true;
    }
    hide(loginNode);
    const overlays = [...document.querySelectorAll('*')].filter((el) => {
      const style = getComputedStyle(el);
      const cr = el.getBoundingClientRect();
      const opacity = Number(style.opacity || 1);
      return (style.position === 'fixed' || style.position === 'absolute') &&
        cr.left <= 5 && cr.top <= 5 &&
        cr.width >= window.innerWidth * 0.8 && cr.height >= window.innerHeight * 0.8 &&
        opacity >= 0.2;
    });
    overlays.forEach(hide);
    return true;
  }
  const fixed = [...document.querySelectorAll('*')].filter((el) => {
    const style = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return style.position === 'fixed' &&
      r.width > 80 && r.height > 40 &&
      (r.left < 40 || r.top < 80 || r.right > window.innerWidth - 40 || r.bottom > window.innerHeight - 40);
  });
  for (const el of fixed) {
    const text = el.innerText || '';
    if (['랭킹', '참가', '라이브', '편집본', '리그', '보상', '카카오로 계속하기', '구글로 계속하기'].some((word) => text.includes(word))) {
      hide(el);
      return true;
    }
  }
  return false;
})()
""",
        )
        if not clicked:
            break
        time.sleep(0.5)


def open_investor_trend(ws):
    found = scroll_inside_panels_to_text(ws, ["투자자별 매매동향", "매매동향"])
    if not found:
        found = scroll_page_to_text(ws, ["투자자별 매매동향", "매매동향"])
    if not found:
        scroll_to_text(ws, ["투자자별 매매동향", "매매동향"])
    time.sleep(0.6)


def scroll_to_text(ws, needles):
    needles_js = json.dumps(needles, ensure_ascii=False)
    return eval_js(
        ws,
        f"""
(() => {{
  const needles = {needles_js};
  const nodes = [...document.querySelectorAll('section,article,div')];
  let best = null;
  for (const el of nodes) {{
    const text = (el.innerText || '').trim();
    if (!text || text.length > 2500) continue;
    if (!needles.some((needle) => text.includes(needle))) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 220 || r.height < 80) continue;
    if (!best || r.width * r.height < best.width * best.height) {{
      best = el;
    }}
  }}
  if (best) {{
    best.scrollIntoView({{block:'center', inline:'nearest'}});
    return true;
  }}
  return false;
}})()
""",
    )


def scroll_inside_panels_to_text(ws, needles):
    needles_js = json.dumps(needles, ensure_ascii=False)
    return eval_js(
        ws,
        f"""
(() => {{
  const needles = {needles_js};
  window.scrollTo(0, 0);
  const visibleText = () => {{
    const nodes = [...document.querySelectorAll('section,article,div')];
    for (const el of nodes) {{
      const text = (el.innerText || '').trim();
      if (!text || text.length > 2500) continue;
      if (!needles.some((needle) => text.includes(needle))) continue;
      const r = el.getBoundingClientRect();
      if (r.width > 220 && r.height > 80 && r.bottom > 100 && r.top < window.innerHeight - 40) {{
        el.scrollIntoView({{block:'center', inline:'nearest'}});
        return true;
      }}
    }}
    return false;
  }};
  if (visibleText()) return true;
  const scrollables = [...document.querySelectorAll('*')].filter((el) => {{
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return el.scrollHeight > el.clientHeight + 80 &&
      r.width > 260 && r.height > 260 &&
      r.left > window.innerWidth * 0.55 &&
      style.display !== 'none' && style.visibility !== 'hidden';
  }});
  for (let top = 0; top <= 5000; top += 360) {{
    for (const el of scrollables) el.scrollTop = top;
    if (visibleText()) return true;
  }}
  return false;
}})()
""",
    )


def scroll_page_to_text(ws, needles):
    needles_js = json.dumps(needles, ensure_ascii=False)
    return eval_js(
        ws,
        f"""
(() => {{
  const needles = {needles_js};
  const visibleText = () => {{
    const nodes = [...document.querySelectorAll('section,article,div')];
    for (const el of nodes) {{
      const text = (el.innerText || '').trim();
      if (!text || text.length > 2500) continue;
      if (!needles.some((needle) => text.includes(needle))) continue;
      const r = el.getBoundingClientRect();
      if (r.width > 220 && r.height > 80 && r.bottom > 100 && r.top < window.innerHeight - 40) {{
        return true;
      }}
    }}
    return false;
  }};
  if (visibleText()) return true;
  const maxTop = Math.max(document.documentElement.scrollHeight, document.body.scrollHeight) - window.innerHeight;
  for (let top = 0; top <= maxTop + 200; top += 420) {{
    window.scrollTo(0, top);
    if (visibleText()) return true;
  }}
  return false;
}})()
""",
    )


def chart_clip(ws):
    rect = eval_js(
        ws,
        """
(() => {
  const nodes = [...document.querySelectorAll('canvas, svg')];
  const visible = nodes
    .map((el) => el.getBoundingClientRect())
    .filter((r) => r.width > 240 && r.height > 120 && r.bottom > 0);
  const r = visible[0];
  if (!r) return null;
  return {
    x: Math.max(0, r.left - 24),
    y: Math.max(0, r.top - 72 + window.scrollY),
    width: Math.min(window.innerWidth, r.width + 48),
    height: Math.min(620, r.height + 150)
  };
})()
""",
    )
    return normalize_clip(rect) or {"x": 0, "y": 0, "width": 1440, "height": 760, "scale": 1}


def investor_clip(ws):
    rect = viewport_text_clip(ws, ["투자자별 매매동향", "누적 순매수", "개인", "기관", "외인"], max_height=620)
    return rect or {"x": 1000, "y": 110, "width": 430, "height": 620, "scale": 1}


def viewport_text_clip(ws, needles, max_height=720):
    needles_js = json.dumps(needles, ensure_ascii=False)
    rect = eval_js(
        ws,
        f"""
(() => {{
  const needles = {needles_js};
  const nodes = [...document.querySelectorAll('section,article,div')];
  let best = null;
  for (const el of nodes) {{
    const text = (el.innerText || '').trim();
    if (!text || text.length > 2200) continue;
    if (!needles.every((needle) => text.includes(needle))) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 260 || r.height < 80 || r.bottom < 80 || r.top > window.innerHeight - 40) continue;
    if (!best || r.width * r.height < best.width * best.height) {{
      best = {{x:r.left, y:r.top, width:r.width, height:r.height}};
    }}
  }}
  if (!best) return null;
  return {{
    x: Math.max(0, best.x - 16),
    y: Math.max(0, best.y - 16),
    width: Math.min(window.innerWidth - Math.max(0, best.x - 16), best.width + 32),
    height: Math.min({max_height}, best.height + 48)
  }};
}})()
""",
    )
    return normalize_clip(rect)


def text_clip(ws, needles, fallback, max_height=720):
    needles_js = json.dumps(needles, ensure_ascii=False)
    rect = eval_js(
        ws,
        f"""
(() => {{
  const needles = {needles_js};
  const nodes = [...document.querySelectorAll('section,article,div')];
  let best = null;
  for (const el of nodes) {{
    const text = (el.innerText || '').trim();
    if (!text || text.length > 2200) continue;
    if (!needles.every((needle) => text.includes(needle))) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 260 || r.height < 80) continue;
    if (!best || r.width * r.height < best.width * best.height) {{
      best = {{x:r.left, y:r.top + window.scrollY, width:r.width, height:r.height}};
    }}
  }}
  if (!best) return null;
  return {{
    x: Math.max(0, best.x - 16),
    y: Math.max(0, best.y - 16),
    width: Math.min(window.innerWidth, best.width + 32),
    height: Math.min({max_height}, best.height + 48)
  }};
}})()
""",
    )
    return normalize_clip(rect) or fallback


def right_panel_clip(y, height):
    return {"x": 1000, "y": y, "width": 430, "height": height, "scale": 1}


def normalize_clip(rect):
    if not isinstance(rect, dict):
        return None
    try:
        return {
            "x": max(0, float(rect["x"])),
            "y": max(0, float(rect["y"])),
            "width": max(100, float(rect["width"])),
            "height": max(100, float(rect["height"])),
            "scale": 1,
        }
    except Exception:
        return None


def save_screenshot(ws, output_dir, filename, label, clip=None, capture_beyond=True):
    params = {"format": "png", "captureBeyondViewport": capture_beyond, "fromSurface": True}
    if clip:
        params["clip"] = clip
    payload = ws.call("Page.captureScreenshot", params)
    data = base64.b64decode(payload["data"])
    path = output_dir / f"{filename}.png"
    path.write_bytes(data)
    return {"label": label, "url": f"/captures/{output_dir.name}/{filename}.png"}


class CDPClient:
    def __init__(self, ws_url):
        parsed = urllib.parse.urlparse(ws_url)
        self.host = parsed.hostname
        self.port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        self.path = parsed.path + (("?" + parsed.query) if parsed.query else "")
        raw = socket.create_connection((self.host, self.port), timeout=8)
        self.sock = ssl.wrap_socket(raw) if parsed.scheme == "wss" else raw
        self.next_id = 1
        self._handshake()

    def _handshake(self):
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
        if b" 101 " not in response:
            raise CaptureError("브라우저 제어 연결에 실패했습니다.")

    def call(self, method, params=None, timeout=15):
        msg_id = self.next_id
        self.next_id += 1
        self._send_json({"id": msg_id, "method": method, "params": params or {}})
        end = time.time() + timeout
        while time.time() < end:
            message = self._recv_json()
            if message.get("id") != msg_id:
                continue
            if "error" in message:
                raise CaptureError(message["error"].get("message", "브라우저 명령 실행에 실패했습니다."))
            return message.get("result", {})
        raise CaptureError("브라우저 응답 시간이 초과되었습니다.")

    def _send_json(self, payload):
        data = json.dumps(payload).encode("utf-8")
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
        self.sock.sendall(bytes(header) + mask + masked)

    def _recv_json(self):
        data = self._recv_frame()
        return json.loads(data.decode("utf-8"))

    def _recv_frame(self):
        first = self._recv_exact(2)
        opcode = first[0] & 0x0F
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        masked = first[1] & 0x80
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length)
        if masked:
            payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        if opcode == 8:
            raise CaptureError("브라우저 연결이 닫혔습니다.")
        if opcode == 9:
            return self._recv_frame()
        return payload

    def _recv_exact(self, length):
        chunks = []
        remaining = length
        while remaining:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise CaptureError("브라우저 연결이 끊겼습니다.")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass
