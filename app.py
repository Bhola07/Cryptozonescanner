"""Crypto Zone Scanner MVP - spot markets, daily candles, High/Low zones.
Run with: streamlit run app.py
"""

import math
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from chart import build_zone_chart
from data import SUPPORTED_EXCHANGES, TIMEFRAME, fetch_daily_ohlcv, gap_report
from db import list_scans, load_scan, save_scan
from engine import filter_completed, scan, taps_for_zones
from exporter import build_detail, build_summary, to_csv_bytes, to_excel_bytes

MARKET = "spot"
DEFAULT_EXCHANGE = "gate"
DEFAULT_PAIR = "BTC/USDT"
DEFAULT_DAYS = 90
DEFAULT_WIDTH = 1.0
HIGH_TINT = "rgba(34, 197, 94, 0.15)"   # green, matches High clusters
LOW_TINT = "rgba(239, 68, 68, 0.15)"    # red, matches Low clusters
EXPORT_TAP_LIMIT = 500_000
MAX_CHART_TAPS = 50_000

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


def build_result(candles, width_pct, meta, forming_dropped):
    zones = scan(candles, width=width_pct / 100)
    zones["occurrences"] = zones["tap_count"] + 1  # reference candle = first occurrence
    return {
        "zones": zones,
        "candles": candles,
        "meta": meta,
        "gaps": gap_report(candles),
        "forming_dropped": forming_dropped,
        "width_pct": width_pct,
    }


def open_saved(scan_id):
    """Reopen a saved search instantly, without fetching from the exchange."""
    row = load_scan(scan_id)
    if row is None:
        return
    st.session_state["exchange"] = row["exchange"]
    st.session_state["pair"] = row["pair"]
    st.session_state["start"] = datetime.fromtimestamp(row["start_ms"] / 1000, timezone.utc).date()
    st.session_state["end"] = (datetime.fromtimestamp(row["end_ms"] / 1000, timezone.utc)
                               - timedelta(days=1)).date()
    st.session_state["width_pct"] = float(row["width_pct"])
    meta = {"exchange": row["exchange"], "market": MARKET,
            "symbol": row["pair"], "timeframe": TIMEFRAME}
    st.session_state["res"] = build_result(row["candles"], row["width_pct"], meta,
                                           row["forming_dropped"])
    st.session_state["res_saved_at"] = row["saved_at"]
    st.session_state["res_restored"] = True


# ---------- Defaults and restore the last search ----------
st.session_state.setdefault("exchange", DEFAULT_EXCHANGE)
st.session_state.setdefault("pair", DEFAULT_PAIR)
st.session_state.setdefault("start", date.today() - timedelta(days=DEFAULT_DAYS))
st.session_state.setdefault("end", date.today())
st.session_state.setdefault("width_pct", DEFAULT_WIDTH)

if "res" not in st.session_state:
    recent = list_scans(1)
    if recent:
        open_saved(recent[0]["id"])

# ---------- Sidebar: New scan and saved searches ----------
with st.sidebar:
    st.header("New scan")
    exchange = st.selectbox("Exchange", SUPPORTED_EXCHANGES, key="exchange")
    pair = st.text_input("Trading pair (spot)", key="pair")
    st.caption(f"Market: {MARKET} · Timeframe: daily ({TIMEFRAME})")
    start = st.date_input("Start date", key="start")
    end = st.date_input("End date", key="end")
    width_pct = st.slider("Zone width (±%)", 0.1, 5.0, step=0.1, key="width_pct")
    run = st.button("Run scan", type="primary", use_container_width=True)

    st.divider()
    st.subheader("Saved searches (all users)")
    saved = list_scans(50)
    if saved:
        saved_labels = {
            r["id"]: (f"{r['exchange']} · {r['pair']} · "
                      f"{datetime.fromtimestamp(r['start_ms'] / 1000, timezone.utc):%Y-%m-%d} → "
                      f"{datetime.fromtimestamp(r['end_ms'] / 1000, timezone.utc):%Y-%m-%d} · "
                      f"±{r['width_pct']}% · saved {r['saved_at']}")
            for r in saved
        }
        pick = st.selectbox("Pick a saved search", list(saved_labels),
                            format_func=lambda i: saved_labels[i], key="recent_pick")
        st.button("Open selected search", use_container_width=True,
                  on_click=open_saved, args=(pick,))
    else:
        st.caption("No saved searches yet. Run a scan and it will appear here.")

# ---------- Run a new scan ----------
if run:
    pair_clean = pair.strip().upper()
    if start >= end:
        st.error("Start date must be before end date.")
    else:
        since_ms, end_ms = utc_ms(start), utc_ms(end + timedelta(days=1))
        try:
            raw, tf_ms = load(exchange, pair_clean, since_ms, end_ms)
        except Exception as e:  # network, rate limit, unlisted pair, etc.
            st.error(f"Could not fetch data: {e}")
        else:
            completed = filter_completed(raw, tf_ms, int(time.time() * 1000))
            dropped = len(raw) - len(completed)
            meta = {"exchange": exchange, "market": MARKET,
                    "symbol": pair_clean, "timeframe": TIMEFRAME}
            try:
                st.session_state["res"] = build_result(completed, width_pct, meta, dropped)
            except ValueError as e:
                st.error(str(e))
            else:
                save_scan(exchange, pair_clean, since_ms, end_ms, width_pct, completed, dropped)
                st.session_state["res_saved_at"] = "just now"
                st.session_state["res_restored"] = False

res = st.session_state.get("res")
if not res:
    st.info("Configure a scan in the sidebar and press Run scan.")
    st.stop()

zones, candles, meta = res["zones"], res["candles"], res["meta"]
width = res["width_pct"] / 100
labels = {
    r["zone_id"]: (f"{r['zone_type']} {fmt_price(r['lower'])}–{fmt_price(r['upper'])} "
                   f"({r['occurrences']} occurrences)")
    for _, r in zones.iterrows()
}
labels_short = {
    r["zone_id"]: (f"{r['zone_type']} {fmt_price(r['lower'])} – {fmt_price(r['upper'])} · "
                   f"{r['occurrences']} occ · {r['reference_time']:%Y-%m-%d}")
    for _, r in zones.iterrows()
}

# ---------- Scan summary ----------
st.subheader(f"{meta['symbol']} · {meta['exchange']} · {meta['market']} · daily")
if st.session_state.get("res_restored"):
    st.info(f"Showing your last saved search (saved {st.session_state.get('res_saved_at')}). "
            "Use Run scan for fresh data.")
st.caption(f"Zone width ±{res['width_pct']:.1f}% · completed candles only · "
           f"{res['forming_dropped']} forming candle(s) excluded")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Reference candles", len(zones) // 2)
c2.metric("Total zones", len(zones))
c3.metric("Total taps", int(zones["tap_count"].sum()))
c4.metric("Highest occurrences", int(zones["occurrences"].max()) if len(zones) else 0)

# ---------- Cluster table: one row per day, High left, Low right ----------
st.subheader("Clusters by day")
t1, t2 = st.columns(2)
show_high_tbl = t1.checkbox("High", value=True, key="table_high")
show_low_tbl = t2.checkbox("Low", value=True, key="table_low")

if not (show_high_tbl or show_low_tbl):
    st.info("Tick High, Low, or both to show clusters.")
    shown = zones.iloc[0:0]
else:
    hi = zones[zones["zone_type"] == "High"].sort_values("ref_index")
    lo = zones[zones["zone_type"] == "Low"].sort_values("ref_index")
    table = pd.DataFrame({"Date": hi["reference_time"].dt.strftime("%Y-%m-%d").to_numpy()})

    high_cols, low_cols = [], []
    if show_high_tbl:
        table["High DH"] = hi["reference_price"].map(fmt_price).to_numpy()
        table["High cluster range"] = [
            f"{fmt_price(a)} – {fmt_price(b)}" for a, b in zip(hi["lower"], hi["upper"])]
        table["High occurrences"] = hi["occurrences"].to_numpy()
        high_cols = ["High DH", "High cluster range", "High occurrences"]
    if show_low_tbl:
        table["Low DL"] = lo["reference_price"].map(fmt_price).to_numpy()
        table["Low cluster range"] = [
            f"{fmt_price(a)} – {fmt_price(b)}" for a, b in zip(lo["lower"], lo["upper"])]
        table["Low occurrences"] = lo["occurrences"].to_numpy()
        low_cols = ["Low DL", "Low cluster range", "Low occurrences"]

    table = table.iloc[::-1].reset_index(drop=True)  # newest day first

    styler = table.style.hide(axis="index")
    if high_cols:
        styler = styler.set_properties(subset=high_cols, **{"background-color": HIGH_TINT})
    if low_cols:
        styler = styler.set_properties(subset=low_cols, **{"background-color": LOW_TINT})
    st.dataframe(styler, use_container_width=True)

    selected_types = [t for t, on in (("High", show_high_tbl), ("Low", show_low_tbl)) if on]
    shown = zones[zones["zone_type"].isin(selected_types)]

# ---------- Zone chart ----------
st.subheader("Zone chart")
max_side = max(int(zones.groupby("zone_type").size().max()), 1) if len(zones) else 1
if st.session_state.get("top_n", 10) > max_side:
    st.session_state["top_n"] = max_side

r1 = st.columns([1, 1, 1, 1, 2])
chart_high = r1[0].checkbox("Show High clusters", value=True, key="chart_high")
chart_low = r1[1].checkbox("Show Low clusters", value=True, key="chart_low")
show_labels = r1[2].checkbox("Show labels", value=True, key="chart_labels")
show_dots = r1[3].checkbox("Show tap dots", value=True, key="chart_dots")
top_n = r1[4].slider("Labelled zones per side (top by occurrences)", 1, max_side,
                     min(10, max_side), key="top_n")

focus_ids = zones.sort_values("occurrences", ascending=False)["zone_id"].tolist()
focus_pick = st.selectbox(
    "Highlight one zone (bold outline, its label and tap dots)",
    ["none"] + focus_ids,
    format_func=lambda z: "None" if z == "none" else labels_short[z],
    key="highlight",
)
highlight_id = None if focus_pick == "none" else focus_pick

ranked_all = zones.sort_values(["occurrences", "reference_time"], ascending=[False, False])
label_ids = set(ranked_all.groupby("zone_type").head(top_n)["zone_id"])
if highlight_id is not None:
    label_ids.add(highlight_id)

dot_zones = zones[zones["zone_id"].isin(label_ids) & (zones["tap_count"] > 0)]
chart_taps = None
if show_dots:
    if int(dot_zones["tap_count"].sum()) <= MAX_CHART_TAPS:
        chart_taps = taps_for_zones(candles, dot_zones, width)
    else:
        st.caption("Too many taps to draw dots. Lower the labelled zones count.")

fig = build_zone_chart(candles, zones, chart_high, chart_low, fmt_price, chart_taps,
                       show_labels=show_labels, show_dots=show_dots,
                       top_n=top_n, highlight_id=highlight_id)
if fig is None:
    st.info("Tick Show High clusters, Show Low clusters, or both.")
else:
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Green = High (left) · Red = Low (right). Labelled boxes = top {top_n} per side "
               "by occurrences; other zones are faint outlines. Dots mark the days a labelled "
               "zone was tapped. Hover any box for its full details.")

# ---------- Zone details ----------
st.subheader("Zone details")
if len(shown):
    sel = st.selectbox("Select a zone", shown["zone_id"].tolist(),
                       format_func=lambda z: labels[z])
    z = zones[zones["zone_id"] == sel].iloc[0]
    d1, d2, d3, d4, d5 = st.columns(5)
    d1.metric("Reference date", z["reference_time"].strftime("%Y-%m-%d"))
    d2.metric("Reference " + z["zone_type"].lower(), fmt_price(z["reference_price"]))
    d3.metric("Zone", f"{fmt_price(z['lower'])} – {fmt_price(z['upper'])}")
    d4.metric("Occurrences", int(z["occurrences"]))
    d5.metric("Taps", int(z["tap_count"]))

    zt = taps_for_zones(candles, zones[zones["zone_id"] == sel], width)[
        ["tap_time", "tap_high", "tap_low", "tested_price"]]
    if len(zt):
        zt = zt.assign(tap_time=zt["tap_time"].dt.strftime("%Y-%m-%d"))
        for col in ["tap_high", "tap_low", "tested_price"]:
            zt[col] = zt[col].map(fmt_price)
        st.dataframe(zt, hide_index=True, use_container_width=True)
    else:
        st.write("No taps for this zone yet (occurrence = the reference candle only).")
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
