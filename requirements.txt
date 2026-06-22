import json
import sqlite3
from pathlib import Path


DB_PATH = Path("portfolio_signal.sqlite3")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS holdings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                code TEXT NOT NULL,
                avg_price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                buy_reason TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                holding_id INTEGER NOT NULL,
                captured_at TEXT NOT NULL,
                data_json TEXT NOT NULL,
                source TEXT NOT NULL,
                source_url TEXT DEFAULT '',
                FOREIGN KEY (holding_id) REFERENCES holdings(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                holding_id INTEGER NOT NULL,
                report_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                signal TEXT NOT NULL,
                report_json TEXT NOT NULL,
                FOREIGN KEY (holding_id) REFERENCES holdings(id) ON DELETE CASCADE
            );
            """
        )
        defaults = {
            "update_interval_hours": "3",
            "data_source_url": "",
            "last_refresh_at": "",
        }
        for key, value in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )


def row_to_dict(row):
    return dict(row) if row else None


def get_settings():
    with connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = {row["key"]: row["value"] for row in rows}
    settings["update_interval_hours"] = int(settings.get("update_interval_hours", "3"))
    return settings


def update_settings(payload):
    allowed = {"update_interval_hours", "data_source_url"}
    with connect() as conn:
        for key, value in payload.items():
            if key in allowed:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, str(value)),
                )
    return get_settings()


def set_setting(key, value):
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


def list_holdings():
    with connect() as conn:
        rows = conn.execute("SELECT * FROM holdings ORDER BY created_at DESC").fetchall()
    return [row_to_dict(row) for row in rows]


def create_holding(payload):
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO holdings (name, code, avg_price, quantity, buy_reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payload["name"].strip(),
                payload["code"].strip(),
                float(payload["avgPrice"]),
                int(payload["quantity"]),
                payload.get("buyReason", "").strip(),
            ),
        )
        row = conn.execute("SELECT * FROM holdings WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_dict(row)


def update_holding(holding_id, payload):
    fields = []
    params = []
    mapping = {
        "name": "name",
        "code": "code",
        "avgPrice": "avg_price",
        "quantity": "quantity",
        "buyReason": "buy_reason",
    }
    for incoming, column in mapping.items():
        if incoming in payload:
            fields.append(f"{column} = ?")
            params.append(payload[incoming])
    if not fields:
        return get_holding(holding_id)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    params.append(holding_id)
    with connect() as conn:
        conn.execute(f"UPDATE holdings SET {', '.join(fields)} WHERE id = ?", params)
    return get_holding(holding_id)


def delete_holding(holding_id):
    with connect() as conn:
        conn.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))


def get_holding(holding_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM holdings WHERE id = ?", (holding_id,)).fetchone()
    return row_to_dict(row)


def save_snapshot(holding_id, captured_at, data):
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO market_snapshots
            (holding_id, captured_at, data_json, source, source_url)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                holding_id,
                captured_at,
                json.dumps(data, ensure_ascii=False),
                data.get("source", "unknown"),
                data.get("sourceUrl", ""),
            ),
        )


def save_report(holding_id, report):
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO reports
            (holding_id, report_date, created_at, signal, report_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                holding_id,
                report["reportDate"],
                report["createdAt"],
                report["signal"],
                json.dumps(report, ensure_ascii=False),
            ),
        )


def latest_reports():
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT r.*
            FROM reports r
            JOIN (
                SELECT holding_id, MAX(created_at) AS max_created_at
                FROM reports
                GROUP BY holding_id
            ) latest
            ON latest.holding_id = r.holding_id AND latest.max_created_at = r.created_at
            ORDER BY r.created_at DESC
            """
        ).fetchall()
    return [json.loads(row["report_json"]) for row in rows]


def reports_for_holding(holding_id):
    with connect() as conn:
        rows = conn.execute(
            "SELECT report_json FROM reports WHERE holding_id = ? ORDER BY created_at DESC",
            (holding_id,),
        ).fetchall()
    return [json.loads(row["report_json"]) for row in rows]
