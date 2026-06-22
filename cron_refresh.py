import datetime as dt
import json
import mimetypes
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import db
from analytics import build_report
from capture_alpha import CaptureError, capture_stock
from collector import fetch_market_data
from service.naver_scraper import cleanup_capture_dir
from service.naver_candidate_service import get_candidates, refresh_candidates
from service.naver_top10_service import get_top10, refresh_top10
from stock_analyzer import AnalysisError, analyze_stock, get_stock_universe


HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
APP_ENV = os.environ.get("APP_ENV", "main").strip().lower()
STATIC_DIR = Path("static")
MEMO_FILE = Path("stock_memos.json")
PURCHASE_FILE = Path("stock_purchases.json")
FAVORITE_FILE = Path("stock_favorites.json")
SALE_FILE = Path("stock_sales.json")
REPORT_COMMENT_FILE = Path("stock_report_comments.json")
# Render 단독 배포에서는 비워둬도 됩니다.
# 나중에 GitHub Pages + Render API로 분리할 때 예:
# CORS_ALLOWED_ORIGINS=https://사용자명.github.io,https://사용자명.github.io/저장소명
CORS_ALLOWED_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]


def load_memos():
    if not MEMO_FILE.exists():
        return []
    try:
        data = json.loads(MEMO_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            normalized = []
            changed = False
            for memo in data:
                if not isinstance(memo, dict):
                    continue
                if "id" not in memo:
                    memo = {**memo, "id": f"{memo.get('ticker', 'memo')}-{memo.get('updatedAt', time.time())}"}
                    changed = True
                normalized.append(memo)
            if changed:
                save_memos(normalized)
            return normalized
    except (OSError, json.JSONDecodeError):
        pass
    return []


def save_memos(memos):
    MEMO_FILE.write_text(json.dumps(memos, ensure_ascii=False, indent=2), encoding="utf-8")


def create_memo(payload):
    ticker = str(payload.get("ticker", "")).strip()
    name = str(payload.get("name", "")).strip()
    note = str(payload.get("note", "")).strip()
    if not ticker or not name:
        raise ValueError("종목 정보가 없습니다.")
    if not note:
        raise ValueError("메모 내용을 입력해 주세요.")

    memos = load_memos()
    now = dt.datetime.now().isoformat(timespec="seconds")
    memos.insert(
        0,
        {
            "id": f"{ticker}-{int(time.time() * 1000)}",
            "ticker": ticker,
            "name": name,
            "note": note,
            "updatedAt": now,
        },
    )

    save_memos(memos)
    return memos


def update_memo(memo_id, payload):
    note = str(payload.get("note", "")).strip()
    if not note:
        raise ValueError("메모 내용을 입력해 주세요.")

    memos = load_memos()
    now = dt.datetime.now().isoformat(timespec="seconds")
    found = False
    for memo in memos:
        if str(memo.get("id")) == str(memo_id):
            memo["note"] = note
            memo["updatedAt"] = now
            found = True
            break
    if not found:
        raise ValueError("수정할 메모를 찾을 수 없습니다.")
    save_memos(memos)
    return memos


def delete_memo(memo_id):
    memos = load_memos()
    kept = [memo for memo in memos if str(memo.get("id")) != str(memo_id)]
    save_memos(kept)
    return kept


def load_purchases():
    if not PURCHASE_FILE.exists():
        return []
    try:
        data = json.loads(PURCHASE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            normalized = []
            changed = False
            for purchase in data:
                if not isinstance(purchase, dict):
                    continue
                if "id" not in purchase:
                    purchase = {
                        **purchase,
                        "id": f"{purchase.get('ticker', 'purchase')}-{purchase.get('purchasedAt', int(time.time() * 1000))}",
                    }
                    changed = True
                normalized.append(purchase)
            if changed:
                save_purchases(normalized)
            return normalized
    except (OSError, json.JSONDecodeError):
        pass
    return []


def save_purchases(purchases):
    PURCHASE_FILE.write_text(json.dumps(purchases, ensure_ascii=False, indent=2), encoding="utf-8")


def create_purchase(payload):
    ticker = str(payload.get("ticker", "")).strip()
    name = str(payload.get("name", "")).strip()
    price = float(payload.get("price") or 0)
    quantity = int(payload.get("quantity") or 0)
    note = str(payload.get("note", "")).strip()
    if not ticker or not name:
        raise ValueError("종목 정보가 없습니다.")
    if price <= 0:
        raise ValueError("구매 가격을 입력해 주세요.")
    if quantity <= 0:
        raise ValueError("구매 수량을 입력해 주세요.")

    now = dt.datetime.now().isoformat(timespec="seconds")
    purchase = {
        "id": f"{ticker}-{int(time.time() * 1000)}",
        "ticker": ticker,
        "name": name,
        "price": price,
        "quantity": quantity,
        "note": note,
        "purchasedAt": now,
    }
    purchases = load_purchases()
    purchases.insert(0, purchase)
    save_purchases(purchases)
    upsert_favorite({"ticker": ticker, "name": name})

    try:
        db.create_holding(
            {
                "name": name,
                "code": ticker,
                "avgPrice": price,
                "quantity": quantity,
                "buyReason": note,
            }
        )
    except Exception:
        pass
    return purchases


def delete_purchase(purchase_id):
    purchases = load_purchases()
    kept = [purchase for purchase in purchases if str(purchase.get("id")) != str(purchase_id)]
    save_purchases(kept)
    return kept


def delete_purchases_by_ticker(ticker):
    purchases = load_purchases()
    kept = [purchase for purchase in purchases if str(purchase.get("ticker")) != str(ticker)]
    save_purchases(kept)
    return kept


def update_purchases_by_ticker(ticker, payload):
    ticker = str(ticker).strip()
    name = str(payload.get("name", "")).strip()
    price = float(payload.get("price") or 0)
    quantity = int(float(payload.get("quantity") or 0))
    note = str(payload.get("note", "")).strip()
    if not ticker or not name:
        raise ValueError("종목 정보가 없습니다.")
    if price <= 0:
        raise ValueError("평단을 입력해 주세요.")
    if quantity <= 0:
        raise ValueError("주수를 입력해 주세요.")

    purchases = [purchase for purchase in load_purchases() if str(purchase.get("ticker")) != ticker]
    purchases.insert(
        0,
        {
            "id": f"{ticker}-{int(time.time() * 1000)}",
            "ticker": ticker,
            "name": name,
            "price": price,
            "quantity": quantity,
            "note": note,
            "purchasedAt": dt.datetime.now().isoformat(timespec="seconds"),
            "adjusted": True,
        },
    )
    save_purchases(purchases)
    return purchases


def load_sales():
    if not SALE_FILE.exists():
        return []
    try:
        data = json.loads(SALE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return []


def save_sales(sales):
    SALE_FILE.write_text(json.dumps(sales, ensure_ascii=False, indent=2), encoding="utf-8")


def create_sale(payload):
    ticker = str(payload.get("ticker", "")).strip()
    name = str(payload.get("name", "")).strip()
    avg_price = float(payload.get("avgPrice") or 0)
    buy_quantity = int(float(payload.get("buyQuantity") or 0))
    sell_price = float(payload.get("sellPrice") or 0)
    sell_quantity = int(float(payload.get("sellQuantity") or 0))
    if not ticker or not name:
        raise ValueError("종목 정보가 없습니다.")
    if avg_price <= 0:
        raise ValueError("평단 정보가 없습니다.")
    if sell_price <= 0:
        raise ValueError("매도가격을 입력해 주세요.")
    if sell_quantity <= 0:
        raise ValueError("매도 주수를 입력해 주세요.")
    if buy_quantity > 0 and sell_quantity > buy_quantity:
        raise ValueError("매도 주수가 보유 주수보다 많습니다.")

    buy_amount = avg_price * sell_quantity
    sell_amount = sell_price * sell_quantity
    profit = sell_amount - buy_amount
    return_rate = (profit / buy_amount * 100) if buy_amount else 0
    now = dt.datetime.now().isoformat(timespec="seconds")
    sale = {
        "id": f"{ticker}-{int(time.time() * 1000)}",
        "ticker": ticker,
        "name": name,
        "avgPrice": avg_price,
        "buyQuantity": buy_quantity,
        "sellPrice": sell_price,
        "sellQuantity": sell_quantity,
        "profit": profit,
        "returnRate": return_rate,
        "soldAt": now,
    }
    sales = load_sales()
    sales.insert(0, sale)
    save_sales(sales)
    return sales


def delete_sale(sale_id):
    sales = load_sales()
    kept = [sale for sale in sales if str(sale.get("id")) != str(sale_id)]
    save_sales(kept)
    return kept


def load_report_comments():
    if not REPORT_COMMENT_FILE.exists():
        return {}
    try:
        data = json.loads(REPORT_COMMENT_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_report_comments(comments):
    REPORT_COMMENT_FILE.write_text(json.dumps(comments, ensure_ascii=False, indent=2), encoding="utf-8")


def update_report_comment(ticker, payload):
    ticker = str(ticker).strip()
    comment = str(payload.get("comment", "")).strip()
    if not ticker:
        raise ValueError("종목코드가 없습니다.")
    comments = load_report_comments()
    if comment:
        comments[ticker] = {
            "comment": comment,
            "updatedAt": dt.datetime.now().isoformat(timespec="seconds"),
        }
    else:
        comments.pop(ticker, None)
    save_report_comments(comments)
    return comments


def load_favorites():
    if not FAVORITE_FILE.exists():
        return []
    try:
        data = json.loads(FAVORITE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return []


def save_favorites(favorites):
    FAVORITE_FILE.write_text(json.dumps(favorites, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_favorite(payload):
    ticker = str(payload.get("ticker", "")).strip()
    name = str(payload.get("name", "")).strip()
    if not ticker or not name:
        raise ValueError("종목 정보가 없습니다.")
    favorites = [item for item in load_favorites() if item.get("ticker") != ticker]
    favorites.insert(
        0,
        {
            "ticker": ticker,
            "name": name,
            "createdAt": dt.datetime.now().isoformat(timespec="seconds"),
        },
    )
    save_favorites(favorites)
    return favorites


def delete_favorite(ticker):
    favorites = [item for item in load_favorites() if str(item.get("ticker")) != str(ticker)]
    save_favorites(favorites)
    return favorites


def json_response(handler, payload, status=200):
    body = json.dumps(safe_json(payload), ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    send_cors_headers(handler)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def send_cors_headers(handler):
    origin = handler.headers.get("Origin", "").rstrip("/")
    if origin and origin in CORS_ALLOWED_ORIGINS:
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Vary", "Origin")
        handler.send_header("Access-Control-Allow-Credentials", "false")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")


def safe_json(value):
    if isinstance(value, dict):
        return {str(key): safe_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_json(item) for item in value]
    if isinstance(value, tuple):
        return [safe_json(item) for item in value]
    if isinstance(value, float) and (value != value):
        return None
    if hasattr(value, "item"):
        try:
            return safe_json(value.item())
        except Exception:
            pass
    return value


def read_json(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if length == 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def generate_reports():
    settings = db.get_settings()
    reports = []
    captured_at = dt.datetime.now().isoformat(timespec="seconds")
    for holding in db.list_holdings():
        market_data = fetch_market_data(holding, settings.get("data_source_url", ""))
        db.save_snapshot(holding["id"], captured_at, market_data)
        report = build_report(holding, market_data)
        db.save_report(holding["id"], report)
        reports.append(report)
    db.set_setting("last_refresh_at", captured_at)
    return reports


def scheduler_loop():
    while True:
        try:
            settings = db.get_settings()
            interval = int(settings.get("update_interval_hours", 3))
            last = settings.get("last_refresh_at") or ""
            due = True
            if last:
                last_dt = dt.datetime.fromisoformat(last)
                due = dt.datetime.now() - last_dt >= dt.timedelta(hours=interval)
            if due and db.list_holdings():
                generate_reports()
        except Exception as exc:
            print(f"Scheduler error: {exc}")
        time.sleep(60)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_OPTIONS(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.send_response(204)
            send_cors_headers(self)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/holdings":
            return json_response(self, db.list_holdings())
        if path == "/api/settings":
            return json_response(self, db.get_settings())
        if path == "/api/memos":
            return json_response(self, load_memos())
        if path == "/api/purchases":
            return json_response(self, load_purchases())
        if path == "/api/sales":
            return json_response(self, load_sales())
        if path == "/api/report-comments":
            return json_response(self, load_report_comments())
        if path == "/api/favorites":
            return json_response(self, load_favorites())
        if path == "/api/app-config":
            return json_response(
                self,
                {
                    "env": APP_ENV,
                    "isDev": APP_ENV == "dev",
                    "title": "Junsu SwingLab_Dev" if APP_ENV == "dev" else "Junsu SwingLab",
                }
            )
        if path in ["/api/rankings", "/api/top10"]:
            try:
                return json_response(self, get_top10())
            except Exception as exc:
                return json_response(self, {"error": f"순위 데이터를 가져올 수 없습니다: {exc}"}, 500)
        if path == "/api/candidates":
            try:
                return json_response(self, get_candidates())
            except Exception as exc:
                return json_response(self, {"error": f"매수 후보 데이터를 가져올 수 없습니다: {exc}"}, 500)
        if path == "/api/reports/latest":
            return json_response(self, db.latest_reports())
        if path.startswith("/api/reports/"):
            holding_id = int(path.rsplit("/", 1)[-1])
            return json_response(self, db.reports_for_holding(holding_id))
        return self.serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/holdings":
            try:
                holding = db.create_holding(read_json(self))
                report = build_report(
                    holding,
                    fetch_market_data(holding, db.get_settings().get("data_source_url", "")),
                )
                db.save_report(holding["id"], report)
                return json_response(self, {"holding": holding, "report": report}, 201)
            except (KeyError, ValueError) as exc:
                return json_response(self, {"error": f"입력값을 확인하세요: {exc}"}, 400)
        if path == "/api/refresh":
            return json_response(self, {"reports": generate_reports()})
        if path == "/api/capture":
            try:
                payload = read_json(self)
                return json_response(self, capture_stock(payload.get("query", "")))
            except CaptureError as exc:
                return json_response(self, {"error": str(exc)}, 400)
            except Exception as exc:
                return json_response(self, {"error": f"캡처 중 오류가 발생했습니다: {exc}"}, 500)
        if path == "/api/analyze":
            try:
                payload = read_json(self)
                return json_response(self, analyze_stock(payload.get("query", ""), payload.get("quoteMode", "NAVER")))
            except AnalysisError as exc:
                return json_response(self, {"error": str(exc), "candidates": exc.candidates}, 400)
            except Exception as exc:
                return json_response(self, {"error": f"분석 중 오류가 발생했습니다: {exc}"}, 500)
        if path == "/api/top10/refresh":
            try:
                return json_response(self, refresh_top10())
            except Exception as exc:
                return json_response(self, {"error": f"TOP10 데이터를 새로고침할 수 없습니다: {exc}"}, 500)
        if path == "/api/candidates/refresh":
            try:
                return json_response(self, refresh_candidates())
            except Exception as exc:
                return json_response(self, {"error": f"매수 후보 데이터를 새로고침할 수 없습니다: {exc}"}, 500)
        if path == "/api/memos":
            try:
                return json_response(self, create_memo(read_json(self)), 201)
            except ValueError as exc:
                return json_response(self, {"error": str(exc)}, 400)
            except Exception as exc:
                return json_response(self, {"error": f"메모 저장 중 오류가 발생했습니다: {exc}"}, 500)
        if path == "/api/purchases":
            try:
                return json_response(self, create_purchase(read_json(self)), 201)
            except ValueError as exc:
                return json_response(self, {"error": str(exc)}, 400)
            except Exception as exc:
                return json_response(self, {"error": f"구매 기록 저장 중 오류가 발생했습니다: {exc}"}, 500)
        if path == "/api/sales":
            try:
                return json_response(self, create_sale(read_json(self)), 201)
            except ValueError as exc:
                return json_response(self, {"error": str(exc)}, 400)
            except Exception as exc:
                return json_response(self, {"error": f"매도 기록 저장 중 오류가 발생했습니다: {exc}"}, 500)
        if path == "/api/favorites":
            try:
                return json_response(self, upsert_favorite(read_json(self)), 201)
            except ValueError as exc:
                return json_response(self, {"error": str(exc)}, 400)
            except Exception as exc:
                return json_response(self, {"error": f"즐겨찾기 저장 중 오류가 발생했습니다: {exc}"}, 500)
        return json_response(self, {"error": "Not found"}, 404)

    def do_PUT(self):
        path = urlparse(self.path).path
        if path == "/api/settings":
            return json_response(self, db.update_settings(read_json(self)))
        if path.startswith("/api/memos/"):
            try:
                memo_id = unquote(path.rsplit("/", 1)[-1])
                return json_response(self, update_memo(memo_id, read_json(self)))
            except ValueError as exc:
                return json_response(self, {"error": str(exc)}, 400)
            except Exception as exc:
                return json_response(self, {"error": f"메모 수정 중 오류가 발생했습니다: {exc}"}, 500)
        if path.startswith("/api/report-comments/"):
            try:
                ticker = unquote(path.rsplit("/", 1)[-1])
                return json_response(self, update_report_comment(ticker, read_json(self)))
            except ValueError as exc:
                return json_response(self, {"error": str(exc)}, 400)
            except Exception as exc:
                return json_response(self, {"error": f"코멘트 저장 중 오류가 발생했습니다: {exc}"}, 500)
        if path.startswith("/api/purchases/by-ticker/"):
            try:
                ticker = unquote(path.rsplit("/", 1)[-1])
                return json_response(self, update_purchases_by_ticker(ticker, read_json(self)))
            except ValueError as exc:
                return json_response(self, {"error": str(exc)}, 400)
            except Exception as exc:
                return json_response(self, {"error": f"보유 종목 수정 중 오류가 발생했습니다: {exc}"}, 500)
        if path.startswith("/api/holdings/"):
            holding_id = int(path.rsplit("/", 1)[-1])
            holding = db.update_holding(holding_id, read_json(self))
            return json_response(self, holding)
        return json_response(self, {"error": "Not found"}, 404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/api/memos/"):
            memo_id = unquote(path.rsplit("/", 1)[-1])
            return json_response(self, delete_memo(memo_id))
        if path.startswith("/api/purchases/by-ticker/"):
            ticker = unquote(path.rsplit("/", 1)[-1])
            return json_response(self, delete_purchases_by_ticker(ticker))
        if path.startswith("/api/purchases/"):
            purchase_id = unquote(path.rsplit("/", 1)[-1])
            return json_response(self, delete_purchase(purchase_id))
        if path.startswith("/api/sales/"):
            sale_id = unquote(path.rsplit("/", 1)[-1])
            return json_response(self, delete_sale(sale_id))
        if path.startswith("/api/favorites/"):
            ticker = unquote(path.rsplit("/", 1)[-1])
            return json_response(self, delete_favorite(ticker))
        if path.startswith("/api/holdings/"):
            holding_id = int(path.rsplit("/", 1)[-1])
            db.delete_holding(holding_id)
            return json_response(self, {"ok": True})
        return json_response(self, {"error": "Not found"}, 404)

    def serve_static(self, path):
        if path == "/":
            path = "/index.html"
        target = (STATIC_DIR / path.lstrip("/")).resolve()
        root = STATIC_DIR.resolve()
        if not str(target).startswith(str(root)) or not target.exists() or target.is_dir():
            self.send_response(404)
            self.end_headers()
            return
        content = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main():
    db.init_db()
    cleanup_capture_dir()
    try:
        universe = get_stock_universe()
        print(f"Loaded pykrx stock universe: {len(universe)} tickers")
    except Exception as exc:
        print(f"Failed to load pykrx stock universe: {exc}")
    threading.Thread(target=scheduler_loop, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        print(f"Portfolio Signal MVP running at http://{HOST}:{PORT}")
    except OSError:
        pass
    server.serve_forever()


if __name__ == "__main__":
    main()
