"""
Shared search history (SQLite).

Every completed scan is saved with its candles, so it can be reopened later
without fetching from the exchange again. There is no login, so the history
is shared: anyone using the app can open any saved search.

Set the ZONE_SCANNER_DB environment variable to choose where the file lives.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

import pandas as pd

DB_PATH = os.environ.get(
    "ZONE_SCANNER_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "scanner_history.db"),
)
MAX_SAVED = 50  # keep the most recent 50 searches
CANDLE_COLS = ["timestamp", "open", "high", "low", "close", "volume"]


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            saved_at TEXT NOT NULL,
            exchange TEXT NOT NULL,
            pair TEXT NOT NULL,
            start_ms INTEGER NOT NULL,
            end_ms INTEGER NOT NULL,
            width_pct REAL NOT NULL,
            forming_dropped INTEGER NOT NULL,
            candles_json TEXT NOT NULL
        )
    """)
    return con


def save_scan(exchange: str, pair: str, start_ms: int, end_ms: int, width_pct: float,
              candles: pd.DataFrame, forming_dropped: int) -> int:
    """Save a scan. An identical search replaces the older copy instead of duplicating it."""
    payload = json.dumps(candles[CANDLE_COLS].to_dict(orient="records"))
    saved_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    con = _connect()
    try:
        with con:
            con.execute(
                "DELETE FROM scans WHERE exchange=? AND pair=? AND start_ms=? "
                "AND end_ms=? AND width_pct=?",
                (exchange, pair, start_ms, end_ms, width_pct),
            )
            cur = con.execute(
                "INSERT INTO scans (saved_at, exchange, pair, start_ms, end_ms, width_pct, "
                "forming_dropped, candles_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (saved_at, exchange, pair, start_ms, end_ms, width_pct,
                 forming_dropped, payload),
            )
            con.execute(
                "DELETE FROM scans WHERE id NOT IN "
                "(SELECT id FROM scans ORDER BY id DESC LIMIT ?)",
                (MAX_SAVED,),
            )
            return cur.lastrowid
    finally:
        con.close()


def list_scans(limit: int = MAX_SAVED) -> list:
    """Most recent saved searches first, without the candle data."""
    con = _connect()
    try:
        rows = con.execute(
            "SELECT id, saved_at, exchange, pair, start_ms, end_ms, width_pct "
            "FROM scans ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    finally:
        con.close()
    return [
        {"id": r[0], "saved_at": r[1], "exchange": r[2], "pair": r[3],
         "start_ms": r[4], "end_ms": r[5], "width_pct": r[6]}
        for r in rows
    ]


def load_scan(scan_id: int):
    """Full saved search, including candles. Returns None if it no longer exists."""
    con = _connect()
    try:
        row = con.execute(
            "SELECT id, saved_at, exchange, pair, start_ms, end_ms, width_pct, "
            "forming_dropped, candles_json FROM scans WHERE id=?", (scan_id,)
        ).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    return {
        "id": row[0], "saved_at": row[1], "exchange": row[2], "pair": row[3],
        "start_ms": row[4], "end_ms": row[5], "width_pct": row[6],
        "forming_dropped": row[7],
        "candles": pd.DataFrame(json.loads(row[8]), columns=CANDLE_COLS),
    }
