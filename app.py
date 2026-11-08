"""Crypto Zone Scanner MVP - spot markets, daily candles, High/Low zones.
Run with: streamlit run app.py
"""

import math
import time
from datetime import date, datetime, timedelta, timezone

import streamlit as st

from chart import build_price_chart
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
labels = {
    r["zone_id"]: (f"{r['zone_type']} {fmt_price(r['lower'])}–{fmt_price(r['upper'])} "
                   f"({r['tap_count']} occurrences)")
    for _, r in zones.iterrows()
}

# ---------- Scan summary ----------
st.subheader(f"{meta['symbol']} · {meta['exchange']} · {meta['market']} · daily")
st.caption(f"Zone width ±{res['width_pct']:.1f}% · completed candles only · "
           f"{res['forming_dropped']} forming candle(s) excluded")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Reference candles", len(zones) // 2)
c2.metric("Total zones", len(zones))
c3.metric("Total recorded taps", int(zones["tap_count"].sum()))
c4.metric("Highest tap count", int(zones["tap_count"].max()) if len(zones) else 0)

# ---------- Cluster table ----------
st.subheader("Clusters")
t1, t2 = st.columns(2)
show_high_tbl = t1.checkbox("High", value=True, key="table_high")
show_low_tbl = t2.checkbox("Low", value=True, key="table_low")

selected_types = [t for t, on in (("High", show_high_tbl), ("Low", show_low_tbl)) if on]
if not selected_types:
    st.info("Tick High, Low, or both to show clusters.")
    shown = zones.iloc[0:0]
else:
    shown = zones[zones["zone_type"].isin(selected_types)]
    table = shown[["reference_time", "zone_type", "reference_price",
                   "lower", "upper", "tap_count"]].copy()
    table["Date"] = table["reference_time"].dt.strftime("%Y-%m-%d")
    table["High/Low"] = table["zone_type"]
    table["DH/DL"] = table["reference_price"].map(fmt_price)
    table["Cluster range"] = table.apply(
        lambda r: f"{fmt_price(r['lower'])} – {fmt_price(r['upper'])}", axis=1)
    table["Occurrences"] = table["tap_count"]
    table = table[["Date", "High/Low", "DH/DL", "Cluster range", "Occurrences"]]
    st.dataframe(table, hide_index=True, use_container_width=True)

# ---------- Price chart ----------
st.subheader("Price chart with clusters")
p1, p2, p3 = st.columns([1, 1, 2])
chart_high = p1.checkbox("Show High clusters", value=True, key="chart_high")
chart_low = p2.checkbox("Show Low clusters", value=True, key="chart_low")
max_occ = max(int(zones["tap_count"].max()) if len(zones) else 0, 1)
min_occ = p3.slider("Minimum occurrences to draw", 0, max_occ, 0, key="min_occ",
                    help="Hide weak clusters to reduce clutter on the chart.")

chart_zones = zones[zones["tap_count"] >= min_occ]
fig = build_price_chart(candles, chart_zones, chart_high, chart_low, fmt_price)
st.plotly_chart(fig, use_container_width=True)
st.caption("Red solid boxes = High clusters · Blue dashed boxes = Low clusters · "
           "where they overlap, the colours blend and both outlines stay visible. "
           "Hover a box for its range and occurrences.")

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
    d4.metric("Occurrences", int(z["tap_count"]))

    zt = taps_for_zones(candles, zones[zones["zone_id"] == sel], width)[
        ["tap_time", "tap_high", "tap_low", "tested_price"]]
    if len(zt):
        zt = zt.assign(tap_time=zt["tap_time"].dt.strftime("%Y-%m-%d"))
        for col in ["tap_high", "tap_low", "tested_price"]:
            zt[col] = zt[col].map(fmt_price)
        st.dataframe(zt, hide_index=True, use_container_width=True)
    else:
        st.write("No qualifying occurrences for this zone.")
else:
    st.write("No zones to show for this selection.")

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
