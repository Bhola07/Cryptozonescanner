"""
Hotspots: the price bands where the most zone taps landed, counting High and Low
zones together.

A band is [price * (1 - width), price * (1 + width)], the same width as the zones.
Each tap is counted once for every band that contains its tested price.
The top bands returned never overlap each other.
"""

import numpy as np
import pandas as pd

HOT_COLS = ["rank", "low", "high", "total_taps", "high_taps", "low_taps",
            "zones_involved", "first_tap", "last_tap"]


def find_hotspots(taps: pd.DataFrame, width: float, top_k: int = 5) -> pd.DataFrame:
    """
    taps: tap records from taps_for_zones(), with tested_price, zone_type,
          zone_id and tap_time columns.
    Returns up to top_k non-overlapping bands, most taps first.
    """
    if taps is None or len(taps) == 0:
        return pd.DataFrame(columns=HOT_COLS)

    prices = np.sort(taps["tested_price"].to_numpy(np.float64))
    centers = np.unique(prices)
    lo = centers * (1 - width)
    hi = centers * (1 + width)
    # Taps inside each band [lo, hi], inclusive on both ends.
    counts = (np.searchsorted(prices, hi, side="right")
              - np.searchsorted(prices, lo, side="left"))

    chosen = []
    for idx in np.argsort(-counts, kind="stable"):
        if len(chosen) >= top_k:
            break
        l, h = lo[idx], hi[idx]
        if any(l <= ch and cl <= h for cl, ch in chosen):
            continue  # overlaps a band already chosen
        chosen.append((l, h))

    rows = []
    for rank, (l, h) in enumerate(chosen, start=1):
        sub = taps[(taps["tested_price"] >= l) & (taps["tested_price"] <= h)]
        rows.append({
            "rank": rank,
            "low": l,
            "high": h,
            "total_taps": len(sub),
            "high_taps": int((sub["zone_type"] == "High").sum()),
            "low_taps": int((sub["zone_type"] == "Low").sum()),
            "zones_involved": int(sub["zone_id"].nunique()),
            "first_tap": sub["tap_time"].min(),
            "last_tap": sub["tap_time"].max(),
        })
    return pd.DataFrame(rows, columns=HOT_COLS)
