"""
Historical OHLCV retrieval through CCXT.

Spot markets and daily candles only. Uses PUBLIC market data; no API keys.
"""

import ccxt
import pandas as pd

# Exchanges from the spec, using CCXT's IDs (Gate.io is "gate" in CCXT).
# Actual availability depends on the CCXT version installed and on whether
# that exchange offers the requested market type.
SUPPORTED_EXCHANGES = [
    "binance", "bybit", "okx", "kucoin", "gate", "poloniex",
    "mexc", "bitget", "kraken", "coinbase",
]

COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
MS_PER_DAY = 86_400_000


TIMEFRAME = "1d"  # daily candles only, per the current scope
TIMEFRAME_MS = 86_400_000


def fetch_daily_ohlcv(exchange_id: str, pair: str, since_ms: int, end_ms: int,
                      limit: int = 1000, max_requests: int = 100):
    """
    Fetch spot daily candles in [since_ms, end_ms) with pagination.

    Returns (df, timeframe_ms). Raises ValueError with a readable message
    if the exchange or pair is not available.
    """
    if not hasattr(ccxt, exchange_id):
        raise ValueError(f"CCXT does not know the exchange '{exchange_id}'.")

    ex = getattr(ccxt, exchange_id)({
        "enableRateLimit": True,  # CCXT throttles requests automatically
        "options": {"defaultType": "spot"},
    })
    ex.load_markets()
    if pair not in ex.markets:
        raise ValueError(f"{pair} is not listed as a spot market on {exchange_id}.")
    if TIMEFRAME not in ex.timeframes:
        raise ValueError(f"{exchange_id} does not offer daily ('1d') candles.")

    rows, cursor, requests = [], since_ms, 0
    while cursor < end_ms and requests < max_requests:
        batch = ex.fetch_ohlcv(pair, TIMEFRAME, since=cursor, limit=limit)
        requests += 1
        if not batch:
            break
        rows.extend(batch)
        next_cursor = batch[-1][0] + TIMEFRAME_MS
        if next_cursor <= cursor:  # no progress from the exchange; stop
            break
        cursor = next_cursor

    df = pd.DataFrame(rows, columns=COLUMNS)
    if not df.empty:
        df = df.drop_duplicates("timestamp").sort_values("timestamp")
        df = df[(df["timestamp"] >= since_ms) & (df["timestamp"] < end_ms)]
    return df.reset_index(drop=True), TIMEFRAME_MS


def gap_report(df: pd.DataFrame, timeframe_ms: int = TIMEFRAME_MS) -> dict:
    """Report missing candles inside the fetched range, so gaps are visible."""
    if len(df) < 2:
        return {"expected": len(df), "actual": len(df), "missing": 0}
    span = int((df["timestamp"].max() - df["timestamp"].min()) // timeframe_ms) + 1
    return {"expected": span, "actual": len(df), "missing": span - len(df)}
