"""Build the two exports from the spec: a summary file and a detailed tap file."""

import io

import pandas as pd

TIME_FMT = "%Y-%m-%d %H:%M"


def build_summary(zones: pd.DataFrame, taps: pd.DataFrame, meta: dict) -> pd.DataFrame:
    """One row per zone, ranked, with tap dates joined into one cell."""
    if taps.empty:
        tap_dates = pd.Series(dtype=object)
    else:
        tap_dates = (
            taps.assign(t=taps["tap_time"].dt.strftime(TIME_FMT))
            .groupby("zone_id")["t"]
            .agg("; ".join)
        )
    out = zones.copy()
    out["reference_date"] = out["reference_time"].dt.strftime(TIME_FMT)
    out["tap_dates"] = out["zone_id"].map(tap_dates).fillna("")
    out = out.assign(**meta)
    return out[[
        "exchange", "market", "symbol", "timeframe", "rank", "zone_type",
        "reference_date", "reference_price", "lower", "upper",
        "tap_count", "tap_dates",
    ]]


def build_detail(taps: pd.DataFrame, meta: dict) -> pd.DataFrame:
    """One row per qualifying tap."""
    out = taps.copy()
    if out.empty:
        out = pd.DataFrame(columns=list(taps.columns) + ["reference_date", "tap_date"])
    else:
        out["reference_date"] = out["reference_time"].dt.strftime(TIME_FMT)
        out["tap_date"] = out["tap_time"].dt.strftime(TIME_FMT)
    out = out.assign(**meta)
    return out[[
        "exchange", "market", "symbol", "timeframe", "zone_type",
        "reference_date", "reference_price", "lower", "upper",
        "tap_date", "tap_high", "tap_low", "tested_price",
    ]]


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def to_excel_bytes(summary: pd.DataFrame, detail: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        detail.to_excel(writer, sheet_name="Taps", index=False)
    return buf.getvalue()
