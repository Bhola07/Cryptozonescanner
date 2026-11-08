"""
Zone calculation and tap detection engine.

Rules (from the MVP spec):
- Every candle produces an independent High zone and an independent Low zone.
  Zone = [price * (1 - width), price * (1 + width)], default width = 1%.
- A High zone is tested only against candle HIGHs.
  A Low zone is tested only against candle LOWs.
- Open and Close are never used.
- Boundaries are inclusive ("falls inside the zone").
- A candle can tap a given zone at most once.
- A zone's own reference candle never taps its own zone.
- All-against-all: every other completed candle is tested, including
  candles BEFORE the reference candle.
- Zones are never merged. Overlapping zones stay separate.

Memory design: scan() returns counts only, so memory stays proportional to
the number of candles. Individual tap records are produced on demand by
taps_for_zones(), for the zone a user selects or for the detail export.
"""

import numpy as np
import pandas as pd

DEFAULT_WIDTH = 0.01
MAX_CANDLES = 5000  # scan cost grows with N^2 but memory stays bounded (counts only)

ZONE_COLS = [
    "zone_id", "zone_type", "ref_index", "reference_time", "reference_price",
    "lower", "upper", "tap_count", "rank",
]
TAP_COLS = [
    "zone_id", "zone_type", "ref_index", "reference_time", "reference_price",
    "lower", "upper", "tap_time", "tap_high", "tap_low", "tested_price",
]


def filter_completed(df: pd.DataFrame, timeframe_ms: int, now_ms: int) -> pd.DataFrame:
    """Keep only candles that have fully closed. The forming candle is dropped."""
    if df.empty:
        return df.copy()
    closes_at = df["timestamp"] + timeframe_ms
    return df[closes_at <= now_ms].reset_index(drop=True)


def _check_size(n: int):
    if n > MAX_CANDLES:
        raise ValueError(
            f"{n} candles exceeds the limit of {MAX_CANDLES}. "
            "Shorten the date range or use a larger timeframe."
        )


def _zone_hits(prices: np.ndarray, width: float, start: int, end: int,
               forward_only: bool = False) -> np.ndarray:
    """
    Boolean matrix for reference rows [start, end):
    hits[a, b] is True when candle b's value falls inside zone (start + a).
    The zone's own reference candle is always excluded.
    If forward_only is True, only candles AFTER the reference candle can tap.
    """
    lower = prices[start:end, None] * (1 - width)
    upper = prices[start:end, None] * (1 + width)
    hits = (prices[None, :] >= lower) & (prices[None, :] <= upper)
    rows = np.arange(end - start)
    ref_idx = start + rows
    if forward_only:
        cols = np.arange(len(prices))
        hits &= cols[None, :] > ref_idx[:, None]
    else:
        hits[rows, ref_idx] = False
    return hits


def scan(df: pd.DataFrame, width: float = DEFAULT_WIDTH, chunk_size: int = 500,
          forward_only: bool = False) -> pd.DataFrame:
    """
    Build all zones and count their taps. Returns one row per zone,
    ranked by tap_count (highest first).
    forward_only=True counts only candles after each reference candle.
    """
    n = len(df)
    _check_size(n)
    if n == 0:
        return pd.DataFrame(columns=ZONE_COLS)

    times = pd.to_datetime(df["timestamp"].to_numpy(np.int64), unit="ms", utc=True)
    frames = []
    for zone_type, col in (("High", "high"), ("Low", "low")):
        prices = df[col].to_numpy(np.float64)
        counts = np.zeros(n, dtype=np.int64)
        for start in range(0, n, chunk_size):
            end = min(start + chunk_size, n)
            counts[start:end] = _zone_hits(prices, width, start, end, forward_only).sum(axis=1)
        frames.append(pd.DataFrame({
            "zone_type": zone_type,
            "ref_index": np.arange(n),
            "reference_time": times,
            "reference_price": prices,
            "lower": prices * (1 - width),
            "upper": prices * (1 + width),
            "tap_count": counts,
        }))

    zones = pd.concat(frames, ignore_index=True)
    zones["zone_id"] = zones["zone_type"] + "-" + zones["ref_index"].astype(str)
    zones = zones.sort_values(
        ["tap_count", "reference_time"], ascending=[False, False]
    ).reset_index(drop=True)
    zones["rank"] = zones.index + 1
    return zones[ZONE_COLS]


def taps_for_zones(df: pd.DataFrame, zones: pd.DataFrame,
                   width: float = DEFAULT_WIDTH, forward_only: bool = False) -> pd.DataFrame:
    """
    Individual tap records for the given zones (a subset of scan() output).
    Each row is one candle that tapped one zone, at most once per zone.
    """
    if zones.empty:
        return pd.DataFrame(columns=TAP_COLS)
    _check_size(len(df))

    times = pd.to_datetime(df["timestamp"].to_numpy(np.int64), unit="ms", utc=True)
    high = df["high"].to_numpy(np.float64)
    low = df["low"].to_numpy(np.float64)
    parts = []

    for zone_type, prices in (("High", high), ("Low", low)):
        wanted = zones.loc[zones["zone_type"] == zone_type, "ref_index"].to_numpy()
        for ref in np.unique(wanted):  # one zone at a time keeps memory bounded
            ref = int(ref)
            hits = _zone_hits(prices, width, ref, ref + 1, forward_only)[0]
            tj = np.nonzero(hits)[0]
            if len(tj) == 0:
                continue
            ref_price = prices[ref]
            parts.append(pd.DataFrame({
                "zone_id": f"{zone_type}-{ref}",
                "zone_type": zone_type,
                "ref_index": ref,
                "reference_time": times[ref],
                "reference_price": ref_price,
                "lower": ref_price * (1 - width),
                "upper": ref_price * (1 + width),
                "tap_time": times[tj],
                "tap_high": high[tj],
                "tap_low": low[tj],
                "tested_price": prices[tj],
            }))

    if not parts:
        return pd.DataFrame(columns=TAP_COLS)
    taps = pd.concat(parts, ignore_index=True)
    return taps.sort_values(["zone_id", "tap_time"]).reset_index(drop=True)[TAP_COLS]
