"""Crypto Zone Scanner MVP - spot markets, daily candles, High/Low zones.
Run with: streamlit run app.py
"""

import math
import time
from datetime import date, datetime, timedelta, timezone

import plotly.express as px
import streamlit as st

from data import SUPPORTED_EXCHANGES, TIMEFRAME, fetch_daily_ohlcv, gap_report
from engine import filter_completed, scan, taps_for_zones
from exporter import build_detail, build_summary, to_csv_bytes, to_excel_bytes

MARKET = "spot"
EXPORT_TAP_LIMIT = 500_000  # full tap exports above this would be too heavy

st.set_page_config(page_title="Crypto Zone Scanner", layout="wide")
st.title("Crypto Zone Scanner — MVP")
st.caption("Historical daily high/low zone tap counter · spot markets · "
           "analysis only, not a trading tool.")


@st.cache_data(ttl=900, show_spinner="Fetching daily candles from exchange...")
def load(exchange, pair, since_ms, end_ms):
    return fetch_daily_ohlcv(exchange, pair, since_ms, end_ms)


def utc_ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def fmt_price(x: float) -> str:
    """Show enough decimals for small prices: 100000 -> '100,000.00', 0.0004 -> '0.00040000'."""
    if x == 0 or not math.isfinite(x):
        return f"{x:,.2f}"
    decimals = min(12, max(2, 4 - math.floor(math.log10(abs(x)))))
    return f"{x:,.{decimals}f}"


# ---------- Sidebar: New Scan ----------
with st.sidebar:
    st.header("New scan")
    exchange = st.selectbox("Exchange", SUPPORTED_EXCHANGES, index=0)
    pair = st.text_input("Trading pair (spot)", "BTC/USDT")
    st.caption(f"Market: {MARKET} · Timeframe: daily ({TIMEFRAME})")

    today = date.today()
    start = st.date_input("Start date", today - timedelta(days=90))
    end = st.date_input("End date", today)
    width_pct = st.slider("Zone width (±%)", 0.1, 5.0, 1.0, 0.1)
    run = st.button("Run scan", type="primary", use_container_width=True)

if run:
    pair = pair.strip().upper()
    if start >= end:
        st.error("Start date must be before end date.")
    else:
        since_ms, end_ms = utc_ms(start), utc_ms(end + timedelta(days=1))
        try:
            raw, tf_ms = load(exchange, pair, since_ms, end_ms)
        except Exception as e:  # network, rate limit, unlisted pair, etc.
            st.error(f"Could not fetch data: {e}")
        else:
            completed = filter_completed(raw, tf_ms, int(time.time() * 1000))
            try:
                zones = scan(completed, width=width_pct / 100)
            except ValueError as e:
                st.error(str(e))
            else:
                st.session_state["res"] = {
                    "zones": zones,
                    "candles": completed,
                    "meta": {"exchange": exchange, "market": MARKET,
                             "symbol": pair, "timeframe": TIMEFRAME},
                    "gaps": gap_report(completed, tf_ms),
                    "forming_dropped": len(raw) - len(completed),
                    "width_pct": width_pct,
                }

res = st.session_state.get("res")
if not res:
    st.info("Configure a scan in the sidebar and press Run scan.")
    st.stop()

zones, candles, meta = res["zones"], res["candles"], res["meta"]
width = res["width_pct"] / 100
zones = zones.assign(
    label=zones.apply(
        lambda r: f"{r['zone_type']} {fmt_price(r['lower'])}–{fmt_price(r['upper'])} "
                  f"({r['tap_count']} occurrences)", axis=1)
)
labels = dict(zip(zones["zone_id"], zones["label"]))

# ---------- Scan summary ----------
st.subheader(f"{meta['symbol']} · {meta['exchange']} · {meta['market']} · daily")
st.caption(f"Zone width ±{res['width_pct']:.1f}% · completed candles only · "
           f"{res['forming_dropped']} forming candle(s) excluded")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Reference candles", len(zones) // 2)
c2.metric("Total zones", len(zones))
c3.metric("Total recorded taps", int(zones["tap_count"].sum()))
c4.metric("Highest tap count", int(zones["tap_count"].max()) if len(zones) else 0)

# ---------- Rankings ----------
view = st.radio("Show zones", ["All", "High", "Low"], horizontal=True)
shown = zones if view == "All" else zones[zones["zone_type"] == view]

table = shown[["zone_type", "lower", "upper", "reference_price",
               "reference_time", "tap_count"]].copy()
table["Cluster range"] = table.apply(
    lambda r: f"{fmt_price(r['lower'])} – {fmt_price(r['upper'])}", axis=1)
table["Daily High/Daily Low"] = table["reference_price"].map(fmt_price)
table["Reference date"] = table["reference_time"].dt.strftime("%Y-%m-%d")
table["Occurrences"] = table["tap_count"]
table["Zone type"] = table["zone_type"]
table = table[["Zone type", "Cluster range", "Daily High/Daily Low", "Reference date", "Occurrences"]]
st.dataframe(table, hide_index=True, use_container_width=True)

if len(shown):
    fig = px.bar(shown.head(20), x="label", y="tap_count", color="zone_type",
                 title="Top 20 zones by tap count")
    fig.update_layout(xaxis_title=None, xaxis_tickangle=-35, height=420)
    st.plotly_chart(fig, use_container_width=True)

# ---------- Zone details ----------
st.subheader("Zone details")
if len(shown):
    sel = st.selectbox("Select a zone", shown["zone_id"].tolist(),
                       format_func=lambda z: labels[z])
    z = zones[zones["zone_id"] == sel].iloc[0]
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Reference date", z["reference_time"].strftime("%Y-%m-%d"))
    d2.metric("Reference " + z["zone_type"].lower(), fmt_price(z["reference_price"]))
    d3.metric("Zone", f"{fmt_price(z['lower'])} – {fmt_price(z['upper'])}")
    d4.metric("Taps", int(z["tap_count"]))

    zt = taps_for_zones(candles, zones[zones["zone_id"] == sel], width)[
        ["tap_time", "tap_high", "tap_low", "tested_price"]]
    if len(zt):
        zt = zt.assign(tap_time=zt["tap_time"].dt.strftime("%Y-%m-%d"))
        for col in ["tap_high", "tap_low", "tested_price"]:
            zt[col] = zt[col].map(fmt_price)
        st.dataframe(zt, hide_index=True, use_container_width=True)
    else:
        st.write("No qualifying taps for this zone.")
else:
    st.write("No zones to show for this filter.")

# ---------- Export ----------
st.subheader("Export")
total_taps = int(zones["tap_count"].sum())
if total_taps > EXPORT_TAP_LIMIT:
    st.info(f"This scan has {total_taps:,} taps, above the export limit of "
            f"{EXPORT_TAP_LIMIT:,}. Use a shorter date range to export.")
else:
    taps = taps_for_zones(candles, zones[zones["tap_count"] > 0], width)
    summary = build_summary(zones, taps, meta)
    detail = build_detail(taps, meta)
    base = f"{meta['exchange']}_spot_{meta['symbol'].replace('/', '-')}_1d"
    e1, e2, e3 = st.columns(3)
    e1.download_button("Summary CSV", to_csv_bytes(summary),
                       f"{base}_summary.csv", "text/csv")
    e2.download_button("Tap detail CSV", to_csv_bytes(detail),
                       f"{base}_taps.csv", "text/csv")
    e3.download_button("Excel (both sheets)", to_excel_bytes(summary, detail),
                       f"{base}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with st.expander("Data quality"):
    g = res["gaps"]
    st.write(f"Expected candles in range: {g['expected']} · Received: {g['actual']} · "
             f"Missing: {g['missing']}")
    if g["missing"] > 0:
        st.warning("Some daily candles are missing from the exchange history. "
                   "Results only reflect the candles that were returned.")
